import SwiftUI

@main
struct PilotWatchApp: App {
    @WKExtensionDelegateAdaptor(PilotWatchExtensionDelegate.self) private var extensionDelegate
    @StateObject private var meetingModel = WatchMeetingModel()

    var body: some Scene {
        WindowGroup {
            WatchMeetingView(
                model: meetingModel,
                transport: meetingModel.transport
            )
        }
    }
}
