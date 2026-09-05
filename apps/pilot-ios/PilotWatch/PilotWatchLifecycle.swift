import Foundation
import WatchKit

@MainActor
final class PilotWatchExtensionDelegate: NSObject, WKExtensionDelegate {
    func handle(_ backgroundTasks: Set<WKRefreshBackgroundTask>) {
        for task in backgroundTasks {
            if let connectivityTask = task as? WKWatchConnectivityRefreshBackgroundTask {
                WatchConnectivityRefreshTaskBroker.shared.accept(connectivityTask)
            } else {
                task.setTaskCompletedWithSnapshot(false)
            }
        }
    }
}

/// Keeps Watch Connectivity refresh time alive until WCSession has activated
/// and consumed its pending content. A bounded deadline still completes the
/// system task before watchOS terminates the app if the phone remains offline.
@MainActor
final class WatchConnectivityRefreshTaskBroker {
    static let shared = WatchConnectivityRefreshTaskBroker()

    private weak var transport: WatchMeetingTransport?
    private var pendingTasks: [ObjectIdentifier: WKWatchConnectivityRefreshBackgroundTask] = [:]
    private var evaluationScheduled = false

    private init() {}

    func register(_ transport: WatchMeetingTransport) {
        self.transport = transport
        transport.prepareForConnectivityBackgroundRefresh()
        evaluate()
    }

    func accept(_ task: WKWatchConnectivityRefreshBackgroundTask) {
        let identifier = ObjectIdentifier(task)
        pendingTasks[identifier] = task
        task.expirationHandler = { [weak self] in
            Task { @MainActor in
                self?.complete(identifier)
            }
        }

        transport?.prepareForConnectivityBackgroundRefresh()
        evaluate()

        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(20))
            self?.complete(identifier)
        }
    }

    func sessionStateDidChange() {
        evaluate()
    }

    private func evaluate() {
        guard !pendingTasks.isEmpty else { return }
        if transport?.canCompleteConnectivityBackgroundRefresh == true {
            for identifier in Array(pendingTasks.keys) {
                complete(identifier)
            }
            return
        }
        scheduleEvaluation()
    }

    private func scheduleEvaluation() {
        guard !evaluationScheduled else { return }
        evaluationScheduled = true
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(250))
            guard let self else { return }
            self.evaluationScheduled = false
            self.evaluate()
        }
    }

    private func complete(_ identifier: ObjectIdentifier) {
        guard let task = pendingTasks.removeValue(forKey: identifier) else { return }
        task.expirationHandler = nil
        task.setTaskCompletedWithSnapshot(false)
    }
}
