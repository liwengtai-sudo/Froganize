import Foundation

public struct AIModelOption: Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String

    public init(id: String, name: String) {
        self.id = id
        self.name = name
    }
}

public enum AIProvider: String, CaseIterable, Codable, Identifiable, Sendable {
    case openRouter
    case alibabaBailian
    case openAI
    case customOpenAICompatible

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .openRouter: return "OpenRouter"
        case .alibabaBailian: return "阿里云百炼"
        case .openAI: return "OpenAI"
        case .customOpenAICompatible: return "通用 API"
        }
    }

    public var apiKeyLabel: String {
        self == .customOpenAICompatible ? "API Key" : "\(displayName) API Key"
    }

    public var environmentVariable: String {
        switch self {
        case .openRouter: return "OPENROUTER_API_KEY"
        case .alibabaBailian: return "DASHSCOPE_API_KEY"
        case .openAI: return "OPENAI_API_KEY"
        case .customOpenAICompatible: return "FROGANIZE_CUSTOM_API_KEY"
        }
    }

    public var models: [AIModelOption] {
        switch self {
        case .openRouter:
            return [
                AIModelOption(id: "qwen/qwen3.7-flash", name: "Qwen 3.7 Flash"),
                AIModelOption(id: "google/gemini-2.5-flash-lite", name: "Gemini 2.5 Flash Lite")
            ]
        case .alibabaBailian:
            return [
                AIModelOption(id: "qwen3.6-flash", name: "Qwen 3.6 Flash"),
                AIModelOption(id: "qwen3.7-plus", name: "Qwen 3.7 Plus")
            ]
        case .openAI:
            return [
                AIModelOption(id: "gpt-5-mini", name: "GPT-5 Mini")
            ]
        case .customOpenAICompatible:
            return [
                AIModelOption(id: "custom-model", name: "自定义模型")
            ]
        }
    }

    public var defaultModel: String {
        models[0].id
    }

    public func supports(model: String) -> Bool {
        if self == .customOpenAICompatible {
            let trimmed = model.trimmingCharacters(in: .whitespacesAndNewlines)
            return model == trimmed
                && !trimmed.isEmpty
                && trimmed.utf8.count <= 256
                && !trimmed.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains)
        }
        return models.contains(where: { $0.id == model })
    }
}

public enum CustomProviderEndpoint {
    public static func validated(_ value: String) -> URL? {
        guard value == value.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty,
              value.utf8.count <= 2_048,
              var components = URLComponents(string: value),
              components.scheme?.lowercased() == "https",
              components.host?.isEmpty == false,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil else {
            return nil
        }
        components.scheme = "https"
        guard let url = components.url, url.absoluteString == value else { return nil }
        return url
    }
}
