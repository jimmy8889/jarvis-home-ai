// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PilotClientKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "PilotClientKit", targets: ["PilotClientKit"]),
    ],
    targets: [
        .target(name: "PilotClientKit"),
        .testTarget(name: "PilotClientKitTests", dependencies: ["PilotClientKit"]),
    ]
)
