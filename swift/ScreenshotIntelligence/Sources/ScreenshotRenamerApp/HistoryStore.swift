import Foundation
import ScreenshotRenamerCore

struct HistoryStore {
    private let fileManager = FileManager.default

    func load() -> [RenameRecord] {
        guard let data = try? Data(contentsOf: historyURL) else { return [] }
        return (try? JSONDecoder.history.decode([RenameRecord].self, from: data)) ?? []
    }

    func save(_ records: [RenameRecord]) throws {
        let directory = historyURL.deletingLastPathComponent()
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try JSONEncoder.pretty.encode(records)
        try data.write(to: historyURL, options: .atomic)
    }

    private var historyURL: URL {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return base
            .appendingPathComponent("AI Screenshot Renamer", isDirectory: true)
            .appendingPathComponent("history.json")
    }
}

private extension JSONEncoder {
    static var pretty: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}

private extension JSONDecoder {
    static var history: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}
