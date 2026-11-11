// swift-tools-version:5.10
import PackageDescription

// OfflineDAoC.app: DaocKit is the tested core (events, the daoc process, models);
// OfflineDAoC is the SwiftUI shell. app/build-app.sh turns the product into the bundle.
let package = Package(
    name: "OfflineDAoC",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "DaocKit"),
        .executableTarget(name: "OfflineDAoC", dependencies: ["DaocKit"]),
        .testTarget(name: "DaocKitTests", dependencies: ["DaocKit"]),
    ]
)
