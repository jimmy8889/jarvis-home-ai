import SwiftUI

@main
struct PilotApp: App {
    @State private var model = PilotModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task {
                    await model.refresh()
                    while !Task.isCancelled {
                        try? await Task.sleep(for: .seconds(20))
                        guard !Task.isCancelled else { return }
                        await model.refresh(silent: true)
                    }
                }
        }
    }
}
