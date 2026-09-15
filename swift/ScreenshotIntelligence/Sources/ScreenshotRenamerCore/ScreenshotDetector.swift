import Foundation

public enum ScreenshotDetector {
    public static let supportedExtensions: Set<String> = ["png", "jpg", "jpeg", "heic", "webp"]

    public static func looksLikeScreenshot(_ url: URL) -> Bool {
        guard supportedExtensions.contains(url.pathExtension.lowercased()) else {
            return false
        }

        let name = url.deletingPathExtension().lastPathComponent
        let patterns = [
            #"^(截图|截屏)\s*\d{4}"#,
            #"^Screenshot\s+\d{4}"#,
            #"^Screen Shot\s+\d{4}"#
        ]

        return patterns.contains { pattern in
            name.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
        }
    }
}
