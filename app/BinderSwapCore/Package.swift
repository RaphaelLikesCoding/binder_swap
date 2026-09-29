// swift-tools-version: 6.0
import PackageDescription

// The collection and trading rules, shared by the iOS app and anything else
// that needs them. Deliberately free of UIKit, SwiftUI and the iOS SDK so it
// builds and tests with the Swift toolchain alone -- no Xcode required, which
// is why this exists before the app does.
let package = Package(
    name: "BinderSwapCore",
    platforms: [.macOS(.v13), .iOS(.v16)],
    products: [.library(name: "BinderSwapCore", targets: ["BinderSwapCore"])],
    targets: [
        .target(name: "BinderSwapCore"),
        .testTarget(name: "BinderSwapCoreTests", dependencies: ["BinderSwapCore"]),
    ]
)
