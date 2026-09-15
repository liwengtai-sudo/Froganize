import Foundation

public struct ScreenshotAnalysis: Codable, Equatable, Sendable {
    public let title: String
    public let summary: String
    public let category: String
    public let confidence: Double
    public let sensitive: Bool

    public init(
        title: String,
        summary: String,
        category: String,
        confidence: Double,
        sensitive: Bool
    ) {
        self.title = title
        self.summary = summary
        self.category = category
        self.confidence = min(max(confidence, 0), 1)
        self.sensitive = sensitive
    }
}

public struct RenameRecord: Codable, Identifiable, Equatable, Sendable {
    public let id: UUID
    public let originalName: String
    public let renamedName: String
    public let directoryPath: String
    public let summary: String
    public let category: String
    public let confidence: Double
    public let sensitive: Bool
    public let createdAt: Date

    public init(
        id: UUID = UUID(),
        originalName: String,
        renamedName: String,
        directoryPath: String,
        analysis: ScreenshotAnalysis,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.originalName = originalName
        self.renamedName = renamedName
        self.directoryPath = directoryPath
        self.summary = analysis.summary
        self.category = analysis.category
        self.confidence = analysis.confidence
        self.sensitive = analysis.sensitive
        self.createdAt = createdAt
    }

    public var originalURL: URL {
        URL(fileURLWithPath: directoryPath).appendingPathComponent(originalName)
    }

    public var renamedURL: URL {
        URL(fileURLWithPath: directoryPath).appendingPathComponent(renamedName)
    }
}
