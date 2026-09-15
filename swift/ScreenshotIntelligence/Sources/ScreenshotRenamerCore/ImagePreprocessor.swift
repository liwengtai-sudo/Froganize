import Foundation
import ImageIO
import UniformTypeIdentifiers

public struct PreparedImage: Sendable {
    public let data: Data
    public let mimeType: String

    public init(data: Data, mimeType: String) {
        self.data = data
        self.mimeType = mimeType
    }
}

public enum ImagePreprocessor {
    public static func prepare(_ url: URL, maxDimension: Int = 2200) throws -> PreparedImage {
        guard let data = try? Data(contentsOf: url, options: [.mappedIfSafe]) else {
            throw OpenAIClientError.unreadableImage
        }
        return try prepare(data, maxDimension: maxDimension)
    }

    /// Prepares already-pinned bytes. Security-sensitive callers should open
    /// and verify a file descriptor first, then use this overload so ImageIO
    /// never resolves a mutable filesystem path.
    public static func prepare(_ data: Data, maxDimension: Int = 2200) throws -> PreparedImage {
        guard !data.isEmpty,
              let source = CGImageSourceCreateWithData(data as CFData, [
            kCGImageSourceShouldCache: false
        ] as CFDictionary) else {
            throw OpenAIClientError.unreadableImage
        }

        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxDimension,
            kCGImageSourceShouldCacheImmediately: true
        ]

        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            throw OpenAIClientError.unreadableImage
        }

        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            output,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else {
            throw OpenAIClientError.unreadableImage
        }

        CGImageDestinationAddImage(destination, thumbnail, [
            kCGImageDestinationLossyCompressionQuality: 0.86
        ] as CFDictionary)

        guard CGImageDestinationFinalize(destination), !output.isEmpty else {
            throw OpenAIClientError.unreadableImage
        }

        return PreparedImage(data: output as Data, mimeType: "image/jpeg")
    }
}
