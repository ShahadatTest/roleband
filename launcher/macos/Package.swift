// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "RoleBandLauncher",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "RoleBandLauncher", targets: ["RoleBandLauncher"]),
    ],
    targets: [
        .target(name: "LauncherChecksCore"),
        .target(name: "LauncherCore", dependencies: ["LauncherChecksCore"], resources: [.process("Resources")]),
        .executableTarget(name: "RoleBandLauncher", dependencies: ["LauncherCore"]),
        .testTarget(name: "LauncherChecksCoreTests", dependencies: ["LauncherChecksCore"]),
        .testTarget(name: "LauncherCoreTests", dependencies: ["LauncherCore"], exclude: ["Fixtures"]),
        .testTarget(name: "LauncherModelTests", dependencies: ["RoleBandLauncher", "LauncherCore"]),
    ]
)
