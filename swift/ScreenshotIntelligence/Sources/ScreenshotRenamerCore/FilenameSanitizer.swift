import Foundation

public enum FilenameSanitizer {
    private static let forbidden = CharacterSet(charactersIn: "/:\\?%*|\"<>：？！“”‘’《》【】（）()，,；;。")
        .union(.controlCharacters)
        .union(.newlines)

    public static func sanitize(_ rawValue: String, maxLength: Int = 36) -> String {
        var value = rawValue
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: #"\.(png|jpe?g|heic|webp)$"#, with: "", options: [.regularExpression, .caseInsensitive])

        value = String(value.unicodeScalars.map { scalar in
            forbidden.contains(scalar) ? " " : String(scalar)
        }.joined())

        value = value
            .split(whereSeparator: { $0.isWhitespace })
            .map(String.init)
            .joined(separator: "-")

        value = value.trimmingCharacters(in: CharacterSet(charactersIn: "-_.，。；：、 "))

        if value.count > maxLength {
            value = String(value.prefix(maxLength))
                .trimmingCharacters(in: CharacterSet(charactersIn: "-_.，。；：、 "))
        }

        return value.isEmpty ? "截图" : value
    }

    public static func destinationURL(
        for originalURL: URL,
        title: String,
        date: Date = Date(),
        fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> URL {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"

        let stem = "\(sanitize(title))-\(formatter.string(from: date))"
        let ext = originalURL.pathExtension.lowercased()
        let directory = originalURL.deletingLastPathComponent()

        func candidate(_ suffix: String = "") -> URL {
            let name = ext.isEmpty ? "\(stem)\(suffix)" : "\(stem)\(suffix).\(ext)"
            return directory.appendingPathComponent(name)
        }

        var result = candidate()
        var index = 2
        while fileExists(result.path) {
            result = candidate("-\(index)")
            index += 1
        }
        return result
    }
}
