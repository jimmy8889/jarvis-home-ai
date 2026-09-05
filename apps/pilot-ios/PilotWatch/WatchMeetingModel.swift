import AVFoundation
import Foundation
import WatchKit

private enum WatchMeetingRecorderStartError: LocalizedError {
    case audioSessionNotActivated
    case recorderUnavailable

    var errorDescription: String? {
        switch self {
        case .audioSessionNotActivated:
            "The Watch microphone route did not become active. Close other audio apps and try again."
        case .recorderUnavailable:
            "The Watch microphone could not start an AAC recording. Close other audio apps and try again."
        }
    }
}

@MainActor
final class WatchMeetingModel: NSObject, ObservableObject {
    private enum EndingReason {
        case stopped
        case interrupted(String)
        case recorderError(String)

        var message: String? {
            switch self {
            case .stopped: nil
            case let .interrupted(message), let .recorderError(message): message
            }
        }
    }

    @Published var draftTitle = WatchMeetingModel.defaultTitle()
    @Published private(set) var captures: [WatchMeetingCapture]
    @Published private(set) var presentation: WatchRecordingPresentation = .idle
    @Published private(set) var elapsedSeconds: TimeInterval = 0
    @Published private(set) var meterLevel: Double = 0
    @Published private(set) var persistenceError: String?

    let transport: WatchMeetingTransport

    private let store: (any WatchMeetingOutboxStoring)?
    private var recorder: AVAudioRecorder?
    private var meterTimer: Timer?
    private var activeCaptureID: UUID?
    private var endingReason: EndingReason = .stopped
    private var isFinalizing = false

    override convenience init() {
        do {
            let value = try WatchMeetingOutboxStore()
            let loadedCaptures = try value.load().sorted { $0.startedAt > $1.startedAt }
            self.init(
                store: value,
                loadedCaptures: loadedCaptures,
                loadError: nil,
                recoverOnLaunch: true
            )
        } catch {
            self.init(
                store: nil,
                loadedCaptures: [],
                loadError: error.localizedDescription,
                recoverOnLaunch: false
            )
        }
    }

    convenience init(
        testingStore: any WatchMeetingOutboxStoring,
        recoverOnLaunch: Bool = false
    ) throws {
        let loadedCaptures = try testingStore.load().sorted { $0.startedAt > $1.startedAt }
        self.init(
            store: testingStore,
            loadedCaptures: loadedCaptures,
            loadError: nil,
            recoverOnLaunch: recoverOnLaunch
        )
    }

    private init(
        store: (any WatchMeetingOutboxStoring)?,
        loadedCaptures: [WatchMeetingCapture],
        loadError: String?,
        recoverOnLaunch: Bool
    ) {
        self.store = store
        captures = loadedCaptures
        persistenceError = loadError
        transport = WatchMeetingTransport()
        super.init()

        transport.captures = { [weak self] in self?.captures ?? [] }
        transport.audioURL = { [weak self] capture in
            self?.store?.audioURL(for: capture) ?? URL(fileURLWithPath: "/invalid")
        }
        transport.updateCapture = { [weak self] captureID, change in
            self?.updateCapture(captureID, change)
        }
        transport.acknowledge = { [weak self] acknowledgement in
            self?.receiveAcknowledgement(acknowledgement)
        }

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(audioSessionInterrupted(_:)),
            name: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance()
        )

        if recoverOnLaunch {
            Task { [weak self] in
                await self?.recoverInterruptedRecordings()
            }
        }
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    var isRecording: Bool {
        presentation == .recording
    }

    var pendingCount: Int {
        captures.filter { capture in
            switch capture.deliveryState {
            case .coreAccepted: false
            case .recording, .queued, .transferring, .durableReceived, .failed: true
            }
        }.count
    }

    var mostRecentCaptures: [WatchMeetingCapture] {
        Array(captures.prefix(8))
    }

    func startRecording() {
        guard recorder == nil,
              !isFinalizing,
              presentation != .requestingPermission,
              presentation != .finalizing
        else { return }
        presentation = .requestingPermission
        persistenceError = nil

        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            beginRecording()
        case .denied:
            failPresentation("Microphone access is off. Enable it in Watch Settings > Privacy & Security > Microphone.")
        case .undetermined:
            AVAudioApplication.requestRecordPermission { [weak self] allowed in
                Task { @MainActor in
                    guard let self else { return }
                    if allowed {
                        self.beginRecording()
                    } else {
                        self.failPresentation("Pilot needs microphone access to record a meeting.")
                    }
                }
            }
        @unknown default:
            failPresentation("Pilot could not determine microphone permission.")
        }
    }

    func stopRecording() {
        guard let recorder, presentation == .recording else { return }
        presentation = .finalizing
        endingReason = .stopped
        persistCurrentDuration(recorder.currentTime)
        recorder.stop()
    }

    func retry(_ captureID: UUID) {
        transport.retry(captureID)
        WKInterfaceDevice.current().play(.retry)
    }

    func resumeDelivery() {
        transport.recoverAndSendPending()
    }

    func clearTransientStatus() {
        switch presentation {
        case .failed, .interrupted:
            presentation = .idle
        case .idle, .requestingPermission, .recording, .finalizing:
            break
        }
    }

    private func beginRecording() {
        guard let store else {
            failPresentation(persistenceError ?? "Pilot could not open its meeting outbox.")
            return
        }

        let captureID = UUID()
        let filename = "\(captureID.uuidString.lowercased()).m4a"
        let capture = WatchMeetingCapture(
            id: captureID,
            title: normalizedTitle,
            startedAt: Date(),
            durationSeconds: 0,
            originalFilename: filename,
            sha256: "",
            sizeBytes: 0,
            deliveryState: .recording,
            attemptCount: 0,
            lastAttemptAt: nil,
            acknowledgedAt: nil,
            coreMeetingID: nil,
            lastError: nil,
            retryable: false
        )

        var capturesWithRecording = captures
        capturesWithRecording.insert(capture, at: 0)
        guard commitCaptures(capturesWithRecording) else {
            failPresentation("Pilot could not reserve durable storage for this recording.")
            return
        }

        Task { [weak self] in
            await self?.activateAndStartRecording(capture: capture, store: store)
        }
    }

    private func activateAndStartRecording(
        capture: WatchMeetingCapture,
        store: any WatchMeetingOutboxStoring
    ) async {
        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.record, mode: .default)
            // watchOS audio routing is asynchronous. setActive(true) may
            // return before the input route is usable, causing AVAudioRecorder
            // to return false even though permission was granted.
            guard try await audioSession.activate() else {
                throw WatchMeetingRecorderStartError.audioSessionNotActivated
            }

            let value = try makeStartedRecorder(
                capture: capture,
                store: store,
                audioSession: audioSession
            )
            store.protectAudio(for: capture)

            recorder = value
            activeCaptureID = capture.id
            elapsedSeconds = 0
            meterLevel = 0
            endingReason = .stopped
            presentation = .recording
            startMeterTimer()
            WKInterfaceDevice.current().play(.start)
        } catch {
            failRecordingStart(capture: capture, store: store, error: error)
        }
    }

    private func makeStartedRecorder(
        capture: WatchMeetingCapture,
        store: any WatchMeetingOutboxStoring,
        audioSession: AVAudioSession
    ) throws -> AVAudioRecorder {
        var sampleRates = [16_000.0]
        let hardwareRate = audioSession.sampleRate
        if hardwareRate > 0,
           !sampleRates.contains(where: { abs($0 - hardwareRate) < 1 }) {
            sampleRates.append(hardwareRate)
        }

        for sampleRate in sampleRates {
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatMPEG4AAC,
                AVSampleRateKey: sampleRate,
                AVNumberOfChannelsKey: 1,
                AVEncoderBitRateKey: 64_000,
                AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
            ]
            let value = try AVAudioRecorder(
                url: store.audioURL(for: capture),
                settings: settings
            )
            value.delegate = self
            value.isMeteringEnabled = true
            if value.prepareToRecord(), value.record() {
                return value
            }
            value.stop()
            _ = value.deleteRecording()
        }
        throw WatchMeetingRecorderStartError.recorderUnavailable
    }

    private func failRecordingStart(
        capture: WatchMeetingCapture,
        store: any WatchMeetingOutboxStoring,
        error: any Error
    ) {
        var capturesWithoutFailedStart = captures
        capturesWithoutFailedStart.removeAll { $0.id == capture.id }
        if commitCaptures(capturesWithoutFailedStart) {
            // Deleting a partially-created audio file is safe only after its
            // manifest entry has been durably removed.
            try? FileManager.default.removeItem(at: store.audioURL(for: capture))
        } else {
            surfaceRetryableStorageFailure(
                captureID: capture.id,
                message: "Pilot could not save recorder cleanup. The local audio was retained for recovery."
            )
        }
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: .notifyOthersOnDeactivation
        )
        failPresentation(error.localizedDescription)
    }

    private var normalizedTitle: String {
        let trimmed = draftTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? Self.defaultTitle() : trimmed
    }

    private static func defaultTitle() -> String {
        "Meeting \(Date().formatted(date: .abbreviated, time: .shortened))"
    }

    private func startMeterTimer() {
        meterTimer?.invalidate()
        meterTimer = Timer.scheduledTimer(
            timeInterval: 0.25,
            target: self,
            selector: #selector(updateMeter),
            userInfo: nil,
            repeats: true
        )
    }

    @objc private func updateMeter() {
        guard let recorder, recorder.isRecording else { return }
        recorder.updateMeters()
        elapsedSeconds = recorder.currentTime
        let decibels = recorder.averagePower(forChannel: 0)
        meterLevel = min(max((Double(decibels) + 55) / 55, 0), 1)
    }

    private func persistCurrentDuration(_ duration: TimeInterval) {
        elapsedSeconds = max(duration, 0)
        guard let activeCaptureID else { return }
        updateCapture(activeCaptureID) { capture in
            capture.durationSeconds = max(duration, capture.durationSeconds)
        }
    }

    private func finishRecording(successfully: Bool) {
        guard !isFinalizing, let activeCaptureID else { return }
        if presentation == .recording, endingReason.message == nil {
            endingReason = .interrupted(
                "The recording stopped unexpectedly. Pilot kept the captured audio."
            )
        }
        isFinalizing = true
        meterTimer?.invalidate()
        meterTimer = nil
        recorder = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        let reason = endingReason
        let capture = captures.first(where: { $0.id == activeCaptureID })
        self.activeCaptureID = nil

        guard successfully, let capture, let store else {
            updateCapture(activeCaptureID) { value in
                value.deliveryState = .failed
                value.retryable = false
                value.lastError = reason.message ?? "The recording could not be finalized."
            }
            isFinalizing = false
            failPresentation(reason.message ?? "The recording could not be finalized.")
            return
        }

        presentation = .finalizing
        Task { [weak self] in
            let result = await Task.detached(priority: .utility) {
                Result { try store.finalizedDetails(for: capture) }
            }.value
            guard let self else { return }
            self.completeFinalization(
                captureID: capture.id,
                result: result,
                endingReason: reason
            )
        }
    }

    private func completeFinalization(
        captureID: UUID,
        result: Result<(duration: TimeInterval, sha256: String, size: Int64), any Error>,
        endingReason: EndingReason
    ) {
        isFinalizing = false
        switch result {
        case let .success(details):
            updateCapture(captureID) { capture in
                capture.durationSeconds = max(details.duration, capture.durationSeconds)
                capture.sha256 = details.sha256
                capture.sizeBytes = details.size
                capture.deliveryState = .queued
                capture.retryable = true
                capture.lastError = endingReason.message
            }
            draftTitle = Self.defaultTitle()
            elapsedSeconds = 0
            meterLevel = 0
            if let message = endingReason.message {
                presentation = .interrupted(message)
                WKInterfaceDevice.current().play(.failure)
            } else {
                presentation = .idle
                WKInterfaceDevice.current().play(.stop)
            }
            transport.recoverAndSendPending()
        case let .failure(error):
            updateCapture(captureID) { capture in
                capture.deliveryState = .failed
                capture.retryable = false
                capture.lastError = error.localizedDescription
            }
            failPresentation(error.localizedDescription)
        }
    }

    private func recoverInterruptedRecordings() async {
        guard let store else { return }
        let interrupted = captures.filter { $0.deliveryState == .recording }
        for capture in interrupted {
            let result = await Task.detached(priority: .utility) {
                Result { try store.finalizedDetails(for: capture) }
            }.value
            switch result {
            case let .success(details):
                updateCapture(capture.id) { value in
                    value.durationSeconds = max(details.duration, value.durationSeconds)
                    value.sha256 = details.sha256
                    value.sizeBytes = details.size
                    value.deliveryState = .queued
                    value.retryable = true
                    value.lastError = "Recovered after the previous recording session ended unexpectedly."
                }
                presentation = .interrupted("Recovered an interrupted meeting recording.")
            case let .failure(error):
                updateCapture(capture.id) { value in
                    value.deliveryState = .failed
                    value.retryable = false
                    value.lastError = "Recovery failed: \(error.localizedDescription)"
                }
                presentation = .failed("An interrupted recording needs attention.")
            }
        }
        transport.recoverAndSendPending()
    }

    func receiveAcknowledgement(_ acknowledgement: WatchMeetingAcknowledgement) {
        guard let capture = captures.first(where: { $0.id == acknowledgement.captureID }) else {
            return
        }
        // Core acceptance is terminal. A late duplicate-transfer callback or
        // stale durable/failed acknowledgement must never recreate a pending
        // capture after its only local audio copy has been removed.
        if capture.deliveryState == .coreAccepted,
           acknowledgement.state != .coreAccepted {
            return
        }
        if let current = capture.acknowledgedAt,
           acknowledgement.acknowledgedAt < current {
            return
        }

        switch acknowledgement.state {
        case .durableReceived:
            updateCapture(capture.id) { value in
                value.deliveryState = .durableReceived
                value.acknowledgedAt = acknowledgement.acknowledgedAt
                value.coreMeetingID = acknowledgement.coreMeetingID ?? value.coreMeetingID
                value.lastError = nil
                value.retryable = false
            }
        case .coreAccepted:
            // Persist the accepted tombstone before removing audio. A crash can
            // therefore leave an extra local file, but can never delete the only
            // copy before Pilot Core has acknowledged durable acceptance.
            let acceptedTombstonePersisted = updateCapture(capture.id) { value in
                value.deliveryState = .coreAccepted
                value.acknowledgedAt = acknowledgement.acknowledgedAt
                value.coreMeetingID = acknowledgement.coreMeetingID ?? value.coreMeetingID
                value.lastError = nil
                value.retryable = false
            }
            guard acceptedTombstonePersisted else {
                surfaceRetryableStorageFailure(
                    captureID: capture.id,
                    message: "Pilot Core accepted this meeting, but the Watch could not save that confirmation. The local audio was retained; retry delivery after storage is available."
                )
                WKInterfaceDevice.current().play(.failure)
                return
            }
            do {
                try store?.removeAudio(for: capture)
            } catch {
                persistenceError = "Core accepted the meeting, but local cleanup failed: \(error.localizedDescription)"
            }
            WKInterfaceDevice.current().play(.success)
        case .failed:
            updateCapture(capture.id) { value in
                value.deliveryState = .failed
                value.acknowledgedAt = acknowledgement.acknowledgedAt
                value.coreMeetingID = acknowledgement.coreMeetingID ?? value.coreMeetingID
                value.lastError = acknowledgement.message ?? "Pilot Core did not accept this meeting."
                value.retryable = acknowledgement.retryable
            }
            WKInterfaceDevice.current().play(.failure)
        }
    }

    @discardableResult
    private func updateCapture(
        _ captureID: UUID,
        _ change: (inout WatchMeetingCapture) -> Void
    ) -> Bool {
        guard let index = captures.firstIndex(where: { $0.id == captureID }) else { return false }
        var proposedCaptures = captures
        change(&proposedCaptures[index])
        return commitCaptures(proposedCaptures)
    }

    @discardableResult
    private func commitCaptures(_ proposedCaptures: [WatchMeetingCapture]) -> Bool {
        guard let store else {
            persistenceError = "Pilot could not open its meeting outbox."
            return false
        }
        do {
            try store.save(proposedCaptures)
            captures = proposedCaptures
            persistenceError = nil
            return true
        } catch {
            persistenceError = error.localizedDescription
            return false
        }
    }

    private func surfaceRetryableStorageFailure(captureID: UUID, message: String) {
        if let index = captures.firstIndex(where: { $0.id == captureID }) {
            // This diagnostic is intentionally in-memory only: the failed
            // candidate manifest must not replace the last durable state.
            captures[index].lastError = message
            captures[index].retryable = true
        }
        persistenceError = message
    }

    private func failPresentation(_ message: String) {
        presentation = .failed(message)
        WKInterfaceDevice.current().play(.failure)
    }

    @objc nonisolated private func audioSessionInterrupted(_ notification: Notification) {
        guard
            let rawValue = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
            AVAudioSession.InterruptionType(rawValue: rawValue) == .began
        else {
            return
        }
        Task { @MainActor [weak self] in
            guard let self, let recorder = self.recorder else { return }
            let message = "Another audio session interrupted the recording. The captured audio was kept."
            self.endingReason = .interrupted(message)
            self.presentation = .finalizing
            self.persistCurrentDuration(recorder.currentTime)
            recorder.stop()
        }
    }
}

extension WatchMeetingModel: AVAudioRecorderDelegate {
    nonisolated func audioRecorderDidFinishRecording(
        _ recorder: AVAudioRecorder,
        successfully flag: Bool
    ) {
        Task { @MainActor [weak self] in
            self?.finishRecording(successfully: flag)
        }
    }

    nonisolated func audioRecorderEncodeErrorDidOccur(
        _ recorder: AVAudioRecorder,
        error: (any Error)?
    ) {
        let message = error?.localizedDescription ?? "The audio encoder stopped unexpectedly."
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.endingReason = .recorderError(message)
            self.persistCurrentDuration(recorder.currentTime)
            recorder.stop()
        }
    }
}
