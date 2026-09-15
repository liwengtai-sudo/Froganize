// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "AIScreenshotRenamer",
    defaultLocalization: "zh-Hans",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "ScreenshotRenamer", targets: ["ScreenshotRenamerApp"]),
        .executable(name: "ScreenshotRenamerSelfTest", targets: ["ScreenshotRenamerSelfTest"])
    ],
    targets: [
        .target(
            name: "ScreenshotRenamerCore",
            path: "Sources/ScreenshotRenamerCore",
            linkerSettings: [
                .linkedFramework("ImageIO"),
                .linkedFramework("UniformTypeIdentifiers")
            ]
        ),
        .executableTarget(
            name: "ScreenshotRenamerApp",
            dependencies: ["ScreenshotRenamerCore"],
            path: "Sources/ScreenshotRenamerApp",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("Security"),
                .linkedFramework("UserNotifications")
            ]
        ),
        .executableTarget(
            name: "ScreenshotRenamerSelfTest",
            dependencies: ["ScreenshotRenamerCore"],
            path: "Sources/ScreenshotRenamerSelfTest"
        )
    ]
)
