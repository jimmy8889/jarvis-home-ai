import Foundation

@MainActor
protocol WatchMeetingCoreServing: Sendable {
    func createMeeting(
        title: String,
        startedAt: Date?,
        sourceCaptureID: String?
    ) async throws -> PilotMeeting
    func meeting(_ meetingID: String) async throws -> PilotMeetingDetail
    func meetingRecordingUploadTicket(
        meetingID: String,
        sha256: String,
        sizeBytes: Int64,
        filename: String
    ) async throws -> MeetingRecordingUploadTicket
    func processMeeting(_ meetingID: String) async throws -> PilotMeeting
}

extension PilotAPI: WatchMeetingCoreServing {}

@MainActor
protocol WatchMeetingInboxServing: AnyObject {
    func start()
    func pendingCaptures() throws -> [WatchMeetingInboxRecord]
    func allCaptures() throws -> [WatchMeetingInboxRecord]
    func fileURL(for captureID: UUID) throws -> URL
    func events() throws -> AsyncStream<WatchMeetingInboxEvent>
    func bindCoreDestination(
        captureID: UUID,
        coreOrigin: String,
        coreDeviceID: String
    ) throws -> WatchMeetingInboxRecord
    func bindCoreMeeting(
        captureID: UUID,
        coreMeetingID: String
    ) throws -> WatchMeetingInboxRecord
    func markUploading(captureID: UUID) throws -> WatchMeetingInboxRecord
    func markUploaded(captureID: UUID) throws -> WatchMeetingInboxRecord
    func markProcessing(captureID: UUID) throws -> WatchMeetingInboxRecord
    func markCoreAccepted(captureID: UUID) throws -> WatchMeetingInboxRecord
    func markCoreFailed(
        captureID: UUID,
        message: String,
        retryable: Bool
    ) throws -> WatchMeetingInboxRecord
}

extension WatchMeetingInbox: WatchMeetingInboxServing {}

@MainActor
protocol MeetingBackgroundUploading: AnyObject {
    var onEvent: ((MeetingBackgroundUploadEvent) -> Void)? { get set }
    var jobs: [MeetingBackgroundUploadJob] { get }

    @discardableResult
    func enqueue(
        captureID: String,
        meetingID: String,
        recordingURL: URL,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket?,
        deviceID: String,
        token: String
    ) throws -> MeetingBackgroundUploadJob

    @discardableResult
    func retryUpload(
        captureID: String,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket?,
        deviceID: String,
        token: String
    ) throws -> MeetingBackgroundUploadJob

    func recover() async throws -> MeetingBackgroundUploadRecovery
    @discardableResult
    func markUploadReconciled(captureID: String) throws -> MeetingBackgroundUploadJob
    func markProcessingStarted(captureID: String) throws
    func markProcessingFailed(captureID: String, message: String) throws
    func markProcessingCompleted(captureID: String) throws
    func removeCompleted(captureID: String) throws
    func job(captureID: String) -> MeetingBackgroundUploadJob?
}

extension MeetingBackgroundUploadCoordinator: MeetingBackgroundUploading {}

struct WatchMeetingDeliveryConfiguration: Sendable {
    let coreURL: URL
    let deviceID: String
    let token: String
    let advertisedUploadEndpoint: String?
}

/// Bridges the Watch's durable inbox to the existing device-authenticated Core
/// meeting flow. Every transition is persisted before the next network step.
/// Neither the Watch nor either JSON ledger stores the iPhone's Core token.
@MainActor
final class WatchMeetingDeliveryPipeline {
    typealias ConfigurationProvider = () throws -> WatchMeetingDeliveryConfiguration
    typealias CoreProvider = () throws -> any WatchMeetingCoreServing

    var onCoreAccepted: ((String) -> Void)?
    var onFailure: ((String) -> Void)?

    private let inbox: any WatchMeetingInboxServing
    private let uploader: any MeetingBackgroundUploading
    private let configurationProvider: ConfigurationProvider
    private let coreProvider: CoreProvider
    private var eventTask: Task<Void, Never>?
    private var retryTasks: [UUID: Task<Void, Never>] = [:]
    private var retryCounts: [UUID: Int] = [:]
    private var activeCaptureIDs = Set<UUID>()
    private var repumpCaptureIDs = Set<UUID>()
    private var processingRequiredCaptureIDs = Set<UUID>()
    private var started = false
    private var didRecoverUploader = false
    private var backgroundSessionCompletionPending = false
    private var backgroundSessionCompletionDeadline: Task<Void, Never>?

    init(
        inbox: any WatchMeetingInboxServing = WatchMeetingInbox.shared,
        uploader: any MeetingBackgroundUploading = MeetingBackgroundUploadCoordinator(),
        configurationProvider: @escaping ConfigurationProvider,
        coreProvider: @escaping CoreProvider
    ) {
        self.inbox = inbox
        self.uploader = uploader
        self.configurationProvider = configurationProvider
        self.coreProvider = coreProvider
    }

    func start() {
        guard !started else { return }
        started = true
        inbox.start()
        uploader.onEvent = { [weak self] event in
            Task { @MainActor [weak self] in
                self?.handleUploaderEvent(event)
            }
        }

        do {
            let stream = try inbox.events()
            eventTask = Task { @MainActor [weak self] in
                for await event in stream {
                    guard !Task.isCancelled, let self else { return }
                    self.handleInboxEvent(event)
                }
            }
        } catch {
            onFailure?(error.localizedDescription)
        }

        Task { @MainActor [weak self] in
            await self?.resumePending()
        }
    }

    /// Called at launch and whenever the iPhone reconnects to Core. Active
    /// system uploads are left alone; failed jobs safely resume from their
    /// persisted upload/process boundary.
    func resumePending() async {
        if !didRecoverUploader {
            do {
                _ = try await uploader.recover()
                didRecoverUploader = true
            } catch {
                onFailure?("Watch meeting upload recovery failed. \(error.localizedDescription)")
                // Do not create a replacement upload until cancellation or
                // adoption of every surviving system task is confirmed.
                return
            }
        }

        cleanupCompletedJobs()
        do {
            for record in try inbox.pendingCaptures() {
                await pumpCapture(record.id)
            }
        } catch {
            onFailure?(error.localizedDescription)
        }
    }

    private func handleInboxEvent(_ event: WatchMeetingInboxEvent) {
        switch event {
        case let .received(record, _):
            enqueuePump(record.id)
        case let .receiveFailed(_, message):
            onFailure?(message)
        case .snapshot, .pipelineUpdated:
            break
        }
    }

    private func handleUploaderEvent(_ event: MeetingBackgroundUploadEvent) {
        switch event {
        case let .processingRequired(job):
            guard let captureID = UUID(uuidString: job.captureID) else { return }
            processingRequiredCaptureIDs.insert(captureID)
            enqueuePump(captureID)
        case let .uploadFailed(job):
            guard let captureID = UUID(uuidString: job.captureID) else { return }
            let message = job.failureMessage ?? "Pilot Core did not accept the recording upload."
            let retryable = Self.uploadFailureIsRetryable(message)
            failCapture(captureID, message: message, retryable: retryable)
            processingRequiredCaptureIDs.remove(captureID)
            completeBackgroundSessionIfDurable()
        case .backgroundSessionEventsFinished:
            backgroundSessionCompletionPending = true
            drainCompletionDerivedProcessing()
            scheduleBackgroundSessionCompletionDeadline()
            completeBackgroundSessionIfDurable()
        case .uploadSucceeded, .processingFailed, .completed:
            // The paired processingRequired event and the process call itself
            // own these state changes, preventing duplicate acknowledgements.
            break
        }
    }

    private func enqueuePump(_ captureID: UUID) {
        Task { @MainActor [weak self] in
            await self?.pumpCapture(captureID)
        }
    }

    private func pumpCapture(_ captureID: UUID) async {
        guard activeCaptureIDs.insert(captureID).inserted else {
            repumpCaptureIDs.insert(captureID)
            return
        }
        defer {
            activeCaptureIDs.remove(captureID)
            PilotWatchBackgroundExecution.shared.end(captureID: captureID)
            if repumpCaptureIDs.remove(captureID) != nil {
                enqueuePump(captureID)
            }
            let state = uploader.job(
                captureID: captureID.uuidString.lowercased()
            )?.state
            if state != .awaitingProcessing, state != .processing {
                processingRequiredCaptureIDs.remove(captureID)
            }
            completeBackgroundSessionIfDurable()
        }

        do {
            var record = try capture(captureID)
            guard record.state != .coreAccepted else {
                cleanupCompletedJob(captureID: captureID, record: record)
                return
            }

            let configuration = try configurationProvider()
            record = try inbox.bindCoreDestination(
                captureID: captureID,
                coreOrigin: Self.canonicalCoreOrigin(configuration.coreURL),
                coreDeviceID: configuration.deviceID
            )
            let core = try coreProvider()

            if record.state == .received {
                let meeting = try await core.createMeeting(
                    title: record.metadata.title,
                    startedAt: record.metadata.startedAt,
                    sourceCaptureID: captureID.uuidString.lowercased()
                )
                record = try inbox.bindCoreMeeting(
                    captureID: captureID,
                    coreMeetingID: meeting.id
                )
            }

            guard let meetingID = record.coreMeetingID else {
                throw WatchMeetingInboxError.invalidCoreMeetingID
            }
            let captureKey = captureID.uuidString.lowercased()

            if uploader.job(captureID: captureKey)?.state == .completed {
                try finishAccepted(captureID: captureID, meetingID: meetingID)
                return
            }

            if uploader.job(captureID: captureKey) == nil {
                let recordingURL = try inbox.fileURL(for: captureID)
                let routing = await uploadRouting(
                    record: record,
                    meetingID: meetingID,
                    configuration: configuration,
                    core: core
                )
                _ = try enqueueUpload(
                    captureID: captureKey,
                    meetingID: meetingID,
                    recordingURL: recordingURL,
                    configuration: configuration,
                    routing: routing
                )
                if record.state == .meetingCreated {
                    _ = try inbox.markUploading(captureID: captureID)
                }
                return
            }

            guard let job = uploader.job(captureID: captureKey) else { return }
            if !job.uploadComplete {
                if record.state == .meetingCreated {
                    record = try inbox.markUploading(captureID: captureID)
                }
                if job.state == .failed {
                    // A successful upload response can be lost while Core has
                    // already stored the recording. Reconcile that durable
                    // state before spending bandwidth on another transfer.
                    if let meeting = try? await core.meeting(meetingID),
                       let storedRecording = meeting.recording,
                       Self.recording(
                           storedRecording,
                           matches: record.metadata
                       ) {
                        _ = try uploader.markUploadReconciled(captureID: captureKey)
                        try advanceInboxToUploaded(captureID)
                        try await processUploadedCapture(
                            captureID: captureID,
                            meetingID: meetingID,
                            core: core
                        )
                        return
                    }

                    let routing = await uploadRouting(
                        record: record,
                        meetingID: meetingID,
                        configuration: configuration,
                        core: core
                    )
                    _ = try retryUpload(
                        captureID: captureKey,
                        configuration: configuration,
                        routing: routing
                    )
                }
                return
            }

            try advanceInboxToUploaded(captureID)
            try await processUploadedCapture(
                captureID: captureID,
                meetingID: meetingID,
                core: core
            )
        } catch {
            let retryable = Self.errorIsRetryable(error)
            persistUploaderFailureIfNeeded(
                captureID: captureID,
                message: error.localizedDescription
            )
            failCapture(
                captureID,
                message: error.localizedDescription,
                retryable: retryable
            )
        }
    }

    private func persistUploaderFailureIfNeeded(captureID: UUID, message: String) {
        let captureKey = captureID.uuidString.lowercased()
        guard let job = uploader.job(captureID: captureKey), job.uploadComplete else {
            return
        }
        do {
            if job.state == .awaitingProcessing {
                try uploader.markProcessingStarted(captureID: captureKey)
            }
            if uploader.job(captureID: captureKey)?.state == .processing {
                try uploader.markProcessingFailed(
                    captureID: captureKey,
                    message: message
                )
            }
        } catch {
            onFailure?(error.localizedDescription)
        }
    }

    private struct UploadRouting {
        let advertisedUploadEndpoint: String?
        let ticket: MeetingRecordingUploadTicket?
    }

    /// Every transfer attempt asks Core for a fresh recording-bound ticket; the
    /// ticket response, rather than the legacy manifest route, chooses whether
    /// storage is off-origin. Older Cores safely fall back to their same-origin
    /// device-authenticated PUT.
    private func uploadRouting(
        record: WatchMeetingInboxRecord,
        meetingID: String,
        configuration: WatchMeetingDeliveryConfiguration,
        core: any WatchMeetingCoreServing
    ) async -> UploadRouting {
        do {
            let ticket = try await core.meetingRecordingUploadTicket(
                meetingID: meetingID,
                sha256: record.metadata.sha256,
                sizeBytes: record.metadata.sizeBytes,
                filename: record.metadata.originalFilename
            )
            guard ticket.isBound(
                toMeetingID: meetingID,
                filename: record.metadata.originalFilename,
                sha256: record.metadata.sha256,
                sizeBytes: record.metadata.sizeBytes
            ) else {
                throw MeetingBackgroundUploadError.invalidUploadTicket
            }
            return UploadRouting(
                advertisedUploadEndpoint: configuration.advertisedUploadEndpoint,
                ticket: ticket
            )
        } catch {
            let safeLegacyEndpoint = MeetingBackgroundUploadCoordinator
                .advertisedEndpointIsOffOrigin(
                    configuration.advertisedUploadEndpoint,
                    coreURL: configuration.coreURL
                )
                ? nil
                : configuration.advertisedUploadEndpoint
            return UploadRouting(
                advertisedUploadEndpoint: safeLegacyEndpoint,
                ticket: nil
            )
        }
    }

    private func enqueueUpload(
        captureID: String,
        meetingID: String,
        recordingURL: URL,
        configuration: WatchMeetingDeliveryConfiguration,
        routing: UploadRouting
    ) throws -> MeetingBackgroundUploadJob {
        do {
            return try uploader.enqueue(
                captureID: captureID,
                meetingID: meetingID,
                recordingURL: recordingURL,
                coreURL: configuration.coreURL,
                advertisedUploadEndpoint: routing.advertisedUploadEndpoint,
                uploadTicket: routing.ticket,
                deviceID: configuration.deviceID,
                token: configuration.token
            )
        } catch MeetingBackgroundUploadError.invalidUploadTicket
            where routing.ticket != nil
        {
            // A malformed or already-expired ticket is never replaced with the
            // permanent credential at its advertised off-origin URL.
            return try uploader.enqueue(
                captureID: captureID,
                meetingID: meetingID,
                recordingURL: recordingURL,
                coreURL: configuration.coreURL,
                advertisedUploadEndpoint: nil,
                uploadTicket: nil,
                deviceID: configuration.deviceID,
                token: configuration.token
            )
        }
    }

    private func retryUpload(
        captureID: String,
        configuration: WatchMeetingDeliveryConfiguration,
        routing: UploadRouting
    ) throws -> MeetingBackgroundUploadJob {
        do {
            return try uploader.retryUpload(
                captureID: captureID,
                coreURL: configuration.coreURL,
                advertisedUploadEndpoint: routing.advertisedUploadEndpoint,
                uploadTicket: routing.ticket,
                deviceID: configuration.deviceID,
                token: configuration.token
            )
        } catch MeetingBackgroundUploadError.invalidUploadTicket
            where routing.ticket != nil
        {
            return try uploader.retryUpload(
                captureID: captureID,
                coreURL: configuration.coreURL,
                advertisedUploadEndpoint: nil,
                uploadTicket: nil,
                deviceID: configuration.deviceID,
                token: configuration.token
            )
        }
    }

    private func processUploadedCapture(
        captureID: UUID,
        meetingID: String,
        core: any WatchMeetingCoreServing
    ) async throws {
        let captureKey = captureID.uuidString.lowercased()
        guard let job = uploader.job(captureID: captureKey) else {
            throw MeetingBackgroundUploadError.jobNotFound(captureKey)
        }
        if job.state == .completed {
            try finishAccepted(captureID: captureID, meetingID: meetingID)
            return
        }

        if job.state != .processing {
            try uploader.markProcessingStarted(captureID: captureKey)
        }
        try advanceInboxToProcessing(captureID)

        do {
            _ = try await core.processMeeting(meetingID)
        } catch {
            // A process request can be accepted by Core and lose its response.
            // Treat only a durable post-recorded state as acknowledgement.
            if let meeting = try? await core.meeting(meetingID),
               Self.coreAcceptedStatuses.contains(meeting.status.lowercased()) {
                try finishAccepted(captureID: captureID, meetingID: meetingID)
                return
            }
            try? uploader.markProcessingFailed(
                captureID: captureKey,
                message: error.localizedDescription
            )
            throw error
        }

        try finishAccepted(captureID: captureID, meetingID: meetingID)
    }

    private func finishAccepted(captureID: UUID, meetingID: String) throws {
        let captureKey = captureID.uuidString.lowercased()
        if let job = uploader.job(captureID: captureKey), job.state != .completed {
            try uploader.markProcessingCompleted(captureID: captureKey)
        }
        let record = try capture(captureID)
        if record.state != .coreAccepted {
            _ = try inbox.markCoreAccepted(captureID: captureID)
        }
        if uploader.job(captureID: captureKey)?.state == .completed {
            try uploader.removeCompleted(captureID: captureKey)
        }
        retryTasks.removeValue(forKey: captureID)?.cancel()
        retryCounts.removeValue(forKey: captureID)
        onCoreAccepted?(meetingID)
    }

    private func advanceInboxToUploaded(_ captureID: UUID) throws {
        var record = try capture(captureID)
        if record.state == .meetingCreated {
            record = try inbox.markUploading(captureID: captureID)
        }
        if record.state == .uploading {
            _ = try inbox.markUploaded(captureID: captureID)
        }
    }

    private func advanceInboxToProcessing(_ captureID: UUID) throws {
        try advanceInboxToUploaded(captureID)
        if try capture(captureID).state == .uploaded {
            _ = try inbox.markProcessing(captureID: captureID)
        }
    }

    private func capture(_ captureID: UUID) throws -> WatchMeetingInboxRecord {
        guard let record = try inbox.allCaptures().first(where: { $0.id == captureID }) else {
            throw WatchMeetingInboxError.unknownCapture(captureID)
        }
        return record
    }

    private func failCapture(_ captureID: UUID, message: String, retryable: Bool) {
        do {
            _ = try inbox.markCoreFailed(
                captureID: captureID,
                message: message,
                retryable: retryable
            )
        } catch {
            onFailure?(error.localizedDescription)
            return
        }
        onFailure?("Watch recording retained on this iPhone. \(message)")
        if retryable { scheduleRetry(captureID) }
    }

    private func scheduleRetry(_ captureID: UUID) {
        guard retryTasks[captureID] == nil else { return }
        let attempt = min(retryCounts[captureID, default: 0], 5)
        retryCounts[captureID] = attempt + 1
        let delay = min(30 * (1 << attempt), 15 * 60)
        retryTasks[captureID] = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self else { return }
            self.retryTasks.removeValue(forKey: captureID)
            await self.pumpCapture(captureID)
        }
    }

    private func cleanupCompletedJobs() {
        let records = (try? inbox.allCaptures()) ?? []
        let recordsByID = Dictionary(uniqueKeysWithValues: records.map { ($0.id, $0) })
        for job in uploader.jobs where job.state == .completed {
            guard let captureID = UUID(uuidString: job.captureID),
                  let record = recordsByID[captureID] else { continue }
            cleanupCompletedJob(captureID: captureID, record: record)
        }
    }

    private func drainCompletionDerivedProcessing() {
        for job in uploader.jobs where job.state == .awaitingProcessing {
            guard let captureID = UUID(uuidString: job.captureID) else { continue }
            processingRequiredCaptureIDs.insert(captureID)
            enqueuePump(captureID)
        }
    }

    private func completeBackgroundSessionIfDurable() {
        guard backgroundSessionCompletionPending else { return }
        let hasUndrainedProcessing = uploader.jobs.contains {
            $0.state == .awaitingProcessing || $0.state == .processing
        }
        guard !hasUndrainedProcessing,
              processingRequiredCaptureIDs.isEmpty else { return }
        finishBackgroundSessionEvents()
    }

    private func scheduleBackgroundSessionCompletionDeadline() {
        guard backgroundSessionCompletionDeadline == nil else { return }
        backgroundSessionCompletionDeadline = Task { @MainActor [weak self] in
            // Keep iOS's background wake for normal /process completion, but
            // always return the system callback within a bounded window. The
            // uploader ledger remains a safe retry point if the request stalls.
            try? await Task.sleep(for: .seconds(25))
            self?.finishBackgroundSessionEvents()
        }
    }

    private func finishBackgroundSessionEvents() {
        guard backgroundSessionCompletionPending else { return }
        backgroundSessionCompletionPending = false
        backgroundSessionCompletionDeadline?.cancel()
        backgroundSessionCompletionDeadline = nil
        PilotBackgroundSessionEvents.shared.complete(
            identifier: MeetingBackgroundUploadCoordinator.backgroundSessionIdentifier
        )
    }

    private func cleanupCompletedJob(
        captureID: UUID,
        record: WatchMeetingInboxRecord
    ) {
        do {
            if record.state != .coreAccepted {
                _ = try inbox.markCoreAccepted(captureID: captureID)
            }
            try uploader.removeCompleted(captureID: captureID.uuidString.lowercased())
        } catch {
            onFailure?(error.localizedDescription)
        }
    }

    private static let coreAcceptedStatuses: Set<String> = [
        "processing", "transcribed", "ready", "failed",
    ]

    private static func uploadFailureIsRetryable(_ message: String) -> Bool {
        !message.localizedCaseInsensitiveContains("credential was rejected")
            && !message.localizedCaseInsensitiveContains("does not have meetings capability")
    }

    private static func recording(
        _ recording: MeetingRecording,
        matches metadata: WatchMeetingTransferMetadata
    ) -> Bool {
        recording.sha256.lowercased() == metadata.sha256.lowercased()
            && Int64(recording.sizeBytes) == metadata.sizeBytes
            && recording.contentType.trimmingCharacters(
                in: .whitespacesAndNewlines
            ).lowercased() == "audio/m4a"
    }

    private static func errorIsRetryable(_ error: Error) -> Bool {
        if case PilotAPIError.authentication = error { return false }
        switch error {
        case MeetingBackgroundUploadError.invalidAdvertisedEndpoint,
             MeetingBackgroundUploadError.invalidRecordingFile,
             WatchMeetingInboxError.invalidMetadata,
             WatchMeetingInboxError.metadataConflict,
             WatchMeetingInboxError.invalidCoreIdentity,
             WatchMeetingInboxError.coreIdentityConflict,
             WatchMeetingInboxError.retainedFileMissing,
             WatchMeetingInboxError.storageUnavailable,
             WatchMeetingInboxError.corruptLedger:
            return false
        default:
            return true
        }
    }

    private static func canonicalCoreOrigin(_ url: URL) -> String {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.path = ""
        components?.query = nil
        components?.fragment = nil
        return components?.url?.absoluteString.trimmingCharacters(
            in: CharacterSet(charactersIn: "/")
        ) ?? url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }
}
