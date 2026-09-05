import SwiftUI

@main
struct PilotApp: App {
    @UIApplicationDelegateAdaptor(PilotApplicationDelegate.self)
    private var applicationDelegate
    @State private var model = PilotModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task {
                    await model.runUpdateLoop()
                }
        }
    }
}
