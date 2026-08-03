import SwiftUI

@main
struct PilotDriveApp: App {
    @State private var model = DriveModel()

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .task { await model.run() }
        }
    }
}
