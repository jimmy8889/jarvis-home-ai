import UIKit

@MainActor
final class PilotBackgroundSessionEvents {
    static let shared = PilotBackgroundSessionEvents()

    private var completionHandlers: [String: () -> Void] = [:]

    func register(identifier: String, completionHandler: @escaping () -> Void) {
        // iOS should not deliver a second completion handler for the same
        // session before the first is drained. If it does, complete the older
        // callback rather than leaking the system's background-launch budget.
        completionHandlers.removeValue(forKey: identifier)?()
        completionHandlers[identifier] = completionHandler
    }

    func complete(identifier: String) {
        if let completion = completionHandlers.removeValue(forKey: identifier) {
            completion()
        }
        // A finish event while no UIApplicationDelegate callback is registered
        // belongs to a foreground/resident session. It must not be carried into
        // a later background-launch generation with the same fixed identifier.
    }
}

/// Extends a Watch Connectivity background wake only until the transferred
/// capture has reached another durable boundary (normally a background upload
/// task or a persisted failure). Expiration never deletes the retained file.
@MainActor
final class PilotWatchBackgroundExecution {
    static let shared = PilotWatchBackgroundExecution()

    private var taskIDs: [UUID: [UIBackgroundTaskIdentifier]] = [:]

    func begin(captureID: UUID) {
        var identifier = UIBackgroundTaskIdentifier.invalid
        identifier = UIApplication.shared.beginBackgroundTask(
            withName: "Pilot Watch meeting \(captureID.uuidString)"
        ) { [weak self] in
            Task { @MainActor in
                self?.end(captureID: captureID, identifier: identifier)
            }
        }
        guard identifier != .invalid else { return }
        taskIDs[captureID, default: []].append(identifier)
    }

    func end(captureID: UUID) {
        guard let identifiers = taskIDs.removeValue(forKey: captureID),
              !identifiers.isEmpty else { return }
        for identifier in identifiers {
            UIApplication.shared.endBackgroundTask(identifier)
        }
    }

    private func end(captureID: UUID, identifier: UIBackgroundTaskIdentifier) {
        guard var identifiers = taskIDs[captureID],
              let index = identifiers.firstIndex(of: identifier) else { return }
        identifiers.remove(at: index)
        taskIDs[captureID] = identifiers.isEmpty ? nil : identifiers
        UIApplication.shared.endBackgroundTask(identifier)
    }
}

@MainActor
final class PilotApplicationDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        handleEventsForBackgroundURLSession identifier: String,
        completionHandler: @escaping () -> Void
    ) {
        guard identifier == MeetingBackgroundUploadCoordinator.backgroundSessionIdentifier else {
            completionHandler()
            return
        }
        PilotBackgroundSessionEvents.shared.register(
            identifier: identifier,
            completionHandler: completionHandler
        )
    }
}
