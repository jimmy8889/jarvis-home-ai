import Foundation
@preconcurrency import WatchConnectivity

private struct WatchConnectivityPropertyList: @unchecked Sendable {
    let value: [String: Any]
}

@MainActor
final class WatchMeetingTransport: NSObject, ObservableObject {
    @Published private(set) var isReachable = false
    @Published private(set) var activationState = WCSessionActivationState.notActivated
    @Published private(set) var lastTransportError: String?

    var captures: (() -> [WatchMeetingCapture])?
    var audioURL: ((WatchMeetingCapture) -> URL)?
    var updateCapture: ((UUID, (inout WatchMeetingCapture) -> Void) -> Void)?
    var acknowledge: ((WatchMeetingAcknowledgement) -> Void)?

    private let session: WCSession?

    override init() {
        session = WCSession.isSupported() ? .default : nil
        super.init()
        session?.delegate = self
        session?.activate()
        refreshState(session)
        WatchConnectivityRefreshTaskBroker.shared.register(self)
    }

    var phoneStatusLabel: String {
        guard session != nil else { return "Unavailable" }
        guard activationState == .activated else { return "Starting link" }
        return isReachable ? "iPhone nearby" : "Background delivery"
    }

    func recoverAndSendPending() {
        guard let session, activationState == .activated else {
            session?.activate()
            return
        }

        let outstandingCaptureIDs = Set(session.outstandingFileTransfers.compactMap { transfer in
            (transfer.file.metadata?["capture_id"] as? String).flatMap(UUID.init(uuidString:))
        })

        for capture in captures?() ?? [] {
            guard capture.hasLocalAudio, !outstandingCaptureIDs.contains(capture.id) else {
                continue
            }

            switch capture.deliveryState {
            case .queued:
                beginTransfer(capture)
            case .transferring:
                // WCSession retains queued transfers across relaunches. If it no
                // longer has this transfer, enqueue the same immutable capture
                // again; the phone deduplicates it by capture_id.
                beginTransfer(capture)
            case .failed where capture.retryable:
                beginTransfer(capture)
            case .recording, .durableReceived, .coreAccepted, .failed:
                break
            }
        }
    }

    var canCompleteConnectivityBackgroundRefresh: Bool {
        guard let session else { return true }
        return session.activationState == .activated && !session.hasContentPending
    }

    func prepareForConnectivityBackgroundRefresh() {
        session?.activate()
        recoverAndSendPending()
    }

    func retry(_ captureID: UUID) {
        guard let capture = captures?().first(where: { $0.id == captureID }) else { return }
        updateCapture?(captureID) { value in
            value.deliveryState = .queued
            value.retryable = true
            value.lastError = nil
        }
        beginTransfer(capture)
    }

    private func beginTransfer(_ originalCapture: WatchMeetingCapture) {
        guard
            let session,
            activationState == .activated,
            let audioURL,
            FileManager.default.fileExists(atPath: audioURL(originalCapture).path)
        else {
            updateCapture?(originalCapture.id) { capture in
                capture.deliveryState = .failed
                capture.retryable = true
                capture.lastError = "The local audio file is unavailable."
            }
            return
        }

        let now = Date()
        updateCapture?(originalCapture.id) { capture in
            capture.deliveryState = .transferring
            capture.attemptCount += 1
            capture.lastAttemptAt = now
            capture.lastError = nil
        }

        let metadata: [String: Any] = [
            "schema_version": WatchMeetingProtocol.transferSchema,
            "capture_id": originalCapture.id.uuidString.lowercased(),
            "title": originalCapture.title,
            "started_at": WatchMeetingProtocol.iso8601String(from: originalCapture.startedAt),
            "duration_seconds": originalCapture.durationSeconds,
            "sha256": originalCapture.sha256,
            "size_bytes": NSNumber(value: originalCapture.sizeBytes),
            "original_filename": originalCapture.originalFilename,
        ]
        session.transferFile(audioURL(originalCapture), metadata: metadata)
    }

    private func receive(_ propertyList: [String: Any]) {
        guard let acknowledgement = WatchMeetingAcknowledgement(propertyList: propertyList) else {
            return
        }
        acknowledge?(acknowledgement)
        WatchConnectivityRefreshTaskBroker.shared.sessionStateDidChange()
    }

    private func refreshState(_ session: WCSession?) {
        activationState = session?.activationState ?? .notActivated
        isReachable = session?.isReachable ?? false
    }
}

extension WatchMeetingTransport: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: (any Error)?
    ) {
        let errorDescription = error?.localizedDescription
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.activationState = activationState
            self.isReachable = session.isReachable
            self.lastTransportError = errorDescription
            if activationState == .activated {
                self.recoverAndSendPending()
            }
            WatchConnectivityRefreshTaskBroker.shared.sessionStateDidChange()
        }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        let reachable = session.isReachable
        Task { @MainActor [weak self] in
            self?.isReachable = reachable
            WatchConnectivityRefreshTaskBroker.shared.sessionStateDidChange()
        }
    }

    nonisolated func session(
        _ session: WCSession,
        didFinish fileTransfer: WCSessionFileTransfer,
        error: (any Error)?
    ) {
        guard
            let idString = fileTransfer.file.metadata?["capture_id"] as? String,
            let captureID = UUID(uuidString: idString)
        else {
            return
        }
        let errorDescription = error?.localizedDescription
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.updateCapture?(captureID) { capture in
                if let errorDescription {
                    guard capture.deliveryState == .queued
                            || capture.deliveryState == .transferring else {
                        return
                    }
                    capture.deliveryState = .failed
                    capture.lastError = errorDescription
                    capture.retryable = true
                } else if capture.deliveryState == .transferring {
                    // File handoff alone is not the deletion boundary. The
                    // durable_received/core_accepted acknowledgements come from
                    // the companion after it persists and uploads the capture.
                    capture.lastError = nil
                }
            }
            WatchConnectivityRefreshTaskBroker.shared.sessionStateDidChange()
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        let payload = WatchConnectivityPropertyList(value: userInfo)
        Task { @MainActor [weak self] in
            self?.receive(payload.value)
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        let payload = WatchConnectivityPropertyList(value: message)
        Task { @MainActor [weak self] in
            self?.receive(payload.value)
        }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        let payload = WatchConnectivityPropertyList(value: applicationContext)
        Task { @MainActor [weak self] in
            self?.receive(payload.value)
        }
    }
}
