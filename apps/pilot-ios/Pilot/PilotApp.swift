import SwiftUI

@main
struct PilotApp: App {
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
