import CoreFoundation
import Foundation

public enum ScreenshotControlAction: String, CaseIterable, Sendable {
    case getState = "get_state"
    case configureFolder = "configure_folder"
    case setProviderModel = "set_provider_model"
    case configureCustomProvider = "configure_custom_provider"
    case setEnabled = "set_enabled"
    case saveAPIKey = "save_api_key"
    case removeAPIKey = "remove_api_key"
    case testConnection = "test_connection"
    case processLatest = "process_latest"
    case undoLatest = "undo_latest"
}

public enum ScreenshotExecutableMode: Equatable, Sendable {
    case graphicalApplication
    case control
    case invalid

    public static func parse(arguments: [String]) -> ScreenshotExecutableMode {
        if arguments.isEmpty { return .graphicalApplication }
        if arguments == ["--control"] { return .control }
        return .invalid
    }
}

/// A deliberately small request value. The API key exists only in memory while a
/// `save_api_key` request is being handled and is never included in a response.
public struct ScreenshotControlRequest: Sendable {
    public let requestID: UUID
    public let action: ScreenshotControlAction
    public let folderPath: String?
    public let provider: AIProvider?
    public let model: String?
    public let enabled: Bool?
    public let consentVersion: Int?
    public let apiKey: String?
    public let endpoint: String?

    fileprivate init(
        requestID: UUID,
        action: ScreenshotControlAction,
        folderPath: String? = nil,
        provider: AIProvider? = nil,
        model: String? = nil,
        enabled: Bool? = nil,
        consentVersion: Int? = nil,
        apiKey: String? = nil,
        endpoint: String? = nil
    ) {
        self.requestID = requestID
        self.action = action
        self.folderPath = folderPath
        self.provider = provider
        self.model = model
        self.enabled = enabled
        self.consentVersion = consentVersion
        self.apiKey = apiKey
        self.endpoint = endpoint
    }
}

public enum ScreenshotControlContractError: LocalizedError, Equatable, Sendable {
    case emptyRequest
    case requestTooLarge
    case invalidJSON
    case duplicateField(String)
    case unknownField(String)
    case missingField(String)
    case invalidField(String)
    case unsupportedSchemaVersion
    case unsupportedAction
    case invalidRequestID
    case invalidProvider
    case invalidModel

    public var code: String {
        switch self {
        case .emptyRequest: return "empty_request"
        case .requestTooLarge: return "request_too_large"
        case .invalidJSON: return "invalid_json"
        case .duplicateField: return "duplicate_field"
        case .unknownField: return "unknown_field"
        case .missingField: return "missing_field"
        case .invalidField: return "invalid_field"
        case .unsupportedSchemaVersion: return "unsupported_schema_version"
        case .unsupportedAction: return "unsupported_action"
        case .invalidRequestID: return "invalid_request_id"
        case .invalidProvider: return "invalid_provider"
        case .invalidModel: return "invalid_model"
        }
    }

    public var errorDescription: String? {
        switch self {
        case .emptyRequest:
            return "控制请求为空"
        case .requestTooLarge:
            return "控制请求超过 64 KiB 安全限制"
        case .invalidJSON:
            return "控制请求不是有效的 JSON 对象"
        case let .duplicateField(field):
            return "控制请求包含重复字段：\(field)"
        case let .unknownField(field):
            return "控制请求包含未知字段：\(field)"
        case let .missingField(field):
            return "控制请求缺少字段：\(field)"
        case let .invalidField(field):
            return "控制请求字段无效：\(field)"
        case .unsupportedSchemaVersion:
            return "截图智能控制协议版本不兼容"
        case .unsupportedAction:
            return "不支持的截图智能操作"
        case .invalidRequestID:
            return "request_id 必须是小写 UUID"
        case .invalidProvider:
            return "AI Provider 不在允许列表中"
        case .invalidModel:
            return "AI 模型不属于所选 Provider"
        }
    }
}

public enum ScreenshotControlContract {
    public static let schemaVersion = 1
    public static let maximumRequestBytes = 64 * 1024
    public static let maximumResponseBytes = 64 * 1024
    public static let consentVersion = 1

    public static func decodeRequest(_ data: Data) throws -> ScreenshotControlRequest {
        guard !data.isEmpty else { throw ScreenshotControlContractError.emptyRequest }
        guard data.count <= maximumRequestBytes else {
            throw ScreenshotControlContractError.requestTooLarge
        }

        let duplicateFields: [String]
        do {
            duplicateFields = try topLevelObjectKeys(in: data)
        } catch let error as ScreenshotControlContractError {
            throw error
        } catch {
            throw ScreenshotControlContractError.invalidJSON
        }
        var seen = Set<String>()
        for field in duplicateFields where !seen.insert(field).inserted {
            throw ScreenshotControlContractError.duplicateField(field)
        }

        let object: [String: Any]
        do {
            guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                throw ScreenshotControlContractError.invalidJSON
            }
            object = value
        } catch let error as ScreenshotControlContractError {
            throw error
        } catch {
            throw ScreenshotControlContractError.invalidJSON
        }

        guard exactInteger(object["schema_version"]) == schemaVersion else {
            if object["schema_version"] == nil {
                throw ScreenshotControlContractError.missingField("schema_version")
            }
            throw ScreenshotControlContractError.unsupportedSchemaVersion
        }
        guard let requestIDValue = object["request_id"] as? String else {
            throw ScreenshotControlContractError.missingField("request_id")
        }
        guard let requestID = UUID(uuidString: requestIDValue),
              requestID.uuidString.lowercased() == requestIDValue else {
            throw ScreenshotControlContractError.invalidRequestID
        }
        guard let actionValue = object["action"] as? String else {
            throw ScreenshotControlContractError.missingField("action")
        }
        guard let action = ScreenshotControlAction(rawValue: actionValue) else {
            throw ScreenshotControlContractError.unsupportedAction
        }

        let common: Set<String> = ["schema_version", "request_id", "action"]
        let actionFields: Set<String>
        switch action {
        case .getState, .processLatest, .undoLatest:
            actionFields = []
        case .configureFolder:
            actionFields = ["folder_path"]
        case .setProviderModel, .testConnection:
            actionFields = ["provider", "model"]
        case .configureCustomProvider:
            actionFields = ["endpoint", "model"]
        case .setEnabled:
            actionFields = ["enabled", "consent_version"]
        case .saveAPIKey:
            actionFields = ["provider", "api_key"]
        case .removeAPIKey:
            actionFields = ["provider"]
        }
        for field in object.keys where !common.union(actionFields).contains(field) {
            throw ScreenshotControlContractError.unknownField(field)
        }

        func requireString(_ field: String) throws -> String {
            guard let raw = object[field] else {
                throw ScreenshotControlContractError.missingField(field)
            }
            guard let value = raw as? String, !value.isEmpty else {
                throw ScreenshotControlContractError.invalidField(field)
            }
            return value
        }

        func requireProvider() throws -> AIProvider {
            let value = try requireString("provider")
            guard let provider = AIProvider(rawValue: value) else {
                throw ScreenshotControlContractError.invalidProvider
            }
            return provider
        }

        func requireModel(for provider: AIProvider) throws -> String {
            let model = try requireString("model")
            guard provider.supports(model: model) else {
                throw ScreenshotControlContractError.invalidModel
            }
            return model
        }

        switch action {
        case .getState, .processLatest, .undoLatest:
            return ScreenshotControlRequest(requestID: requestID, action: action)
        case .configureFolder:
            let path = try requireString("folder_path")
            guard path.utf8.count <= 4_096, path.hasPrefix("/"), !path.contains("\0") else {
                throw ScreenshotControlContractError.invalidField("folder_path")
            }
            return ScreenshotControlRequest(
                requestID: requestID,
                action: action,
                folderPath: path
            )
        case .setProviderModel, .testConnection:
            let provider = try requireProvider()
            return ScreenshotControlRequest(
                requestID: requestID,
                action: action,
                provider: provider,
                model: try requireModel(for: provider)
            )
        case .configureCustomProvider:
            let endpoint = try requireString("endpoint")
            guard CustomProviderEndpoint.validated(endpoint) != nil else {
                throw ScreenshotControlContractError.invalidField("endpoint")
            }
            let provider = AIProvider.customOpenAICompatible
            return ScreenshotControlRequest(
                requestID: requestID,
                action: action,
                provider: provider,
                model: try requireModel(for: provider),
                endpoint: endpoint
            )
        case .setEnabled:
            guard let enabled = exactBoolean(object["enabled"]) else {
                if object["enabled"] == nil {
                    throw ScreenshotControlContractError.missingField("enabled")
                }
                throw ScreenshotControlContractError.invalidField("enabled")
            }
            guard let consent = exactInteger(object["consent_version"]) else {
                if object["consent_version"] == nil {
                    throw ScreenshotControlContractError.missingField("consent_version")
                }
                throw ScreenshotControlContractError.invalidField("consent_version")
            }
            guard (enabled && consent == consentVersion) || (!enabled && consent == 0) else {
                throw ScreenshotControlContractError.invalidField("consent_version")
            }
            return ScreenshotControlRequest(
                requestID: requestID,
                action: action,
                enabled: enabled,
                consentVersion: consent
            )
        case .saveAPIKey:
            let provider = try requireProvider()
            let apiKey = try requireString("api_key")
            guard apiKey == apiKey.trimmingCharacters(in: .whitespacesAndNewlines),
                  apiKey.count > 20,
                  apiKey.utf8.count <= 8_192,
                  !apiKey.contains("\n"),
                  !apiKey.contains("\r"),
                  !apiKey.contains("\0") else {
                throw ScreenshotControlContractError.invalidField("api_key")
            }
            return ScreenshotControlRequest(
                requestID: requestID,
                action: action,
                provider: provider,
                apiKey: apiKey
            )
        case .removeAPIKey:
            return ScreenshotControlRequest(
                requestID: requestID,
                action: action,
                provider: try requireProvider()
            )
        }
    }

    private static func exactInteger(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let double = number.doubleValue
        guard double.rounded() == double,
              double >= Double(Int.min), double <= Double(Int.max) else { return nil }
        return Int(double)
    }

    private static func exactBoolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    /// Returns top-level object keys without first collapsing duplicate keys.
    /// It is a validating scanner rather than a second general-purpose parser;
    /// Foundation still performs the authoritative JSON decoding afterwards.
    private static func topLevelObjectKeys(in data: Data) throws -> [String] {
        guard let source = String(data: data, encoding: .utf8) else {
            throw ScreenshotControlContractError.invalidJSON
        }
        var index = source.startIndex

        func skipWhitespace() {
            while index < source.endIndex, source[index].isWhitespace {
                index = source.index(after: index)
            }
        }

        func parseString() throws -> String {
            guard index < source.endIndex, source[index] == "\"" else {
                throw ScreenshotControlContractError.invalidJSON
            }
            let start = index
            index = source.index(after: index)
            var escaped = false
            while index < source.endIndex {
                let character = source[index]
                index = source.index(after: index)
                if escaped {
                    escaped = false
                } else if character == "\\" {
                    escaped = true
                } else if character == "\"" {
                    let token = String(source[start..<index])
                    guard let tokenData = token.data(using: .utf8),
                          let decoded = try? JSONDecoder().decode(String.self, from: tokenData) else {
                        throw ScreenshotControlContractError.invalidJSON
                    }
                    return decoded
                } else if character.unicodeScalars.contains(where: { $0.value < 0x20 }) {
                    throw ScreenshotControlContractError.invalidJSON
                }
            }
            throw ScreenshotControlContractError.invalidJSON
        }

        func skipValue() throws {
            skipWhitespace()
            guard index < source.endIndex else { throw ScreenshotControlContractError.invalidJSON }
            if source[index] == "\"" {
                _ = try parseString()
                return
            }
            if source[index] == "{" || source[index] == "[" {
                let opening = source[index]
                let closing: Character = opening == "{" ? "}" : "]"
                var stack: [Character] = [closing]
                index = source.index(after: index)
                var inString = false
                var escaped = false
                while index < source.endIndex, !stack.isEmpty {
                    let character = source[index]
                    index = source.index(after: index)
                    if inString {
                        if escaped { escaped = false }
                        else if character == "\\" { escaped = true }
                        else if character == "\"" { inString = false }
                        continue
                    }
                    if character == "\"" { inString = true }
                    else if character == "{" { stack.append("}") }
                    else if character == "[" { stack.append("]") }
                    else if character == "}" || character == "]" {
                        guard stack.last == character else {
                            throw ScreenshotControlContractError.invalidJSON
                        }
                        stack.removeLast()
                    }
                }
                guard stack.isEmpty, !inString else {
                    throw ScreenshotControlContractError.invalidJSON
                }
                return
            }
            let start = index
            while index < source.endIndex,
                  source[index] != ",", source[index] != "}" {
                index = source.index(after: index)
            }
            guard !source[start..<index].trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw ScreenshotControlContractError.invalidJSON
            }
        }

        skipWhitespace()
        guard index < source.endIndex, source[index] == "{" else {
            throw ScreenshotControlContractError.invalidJSON
        }
        index = source.index(after: index)
        var keys: [String] = []
        skipWhitespace()
        if index < source.endIndex, source[index] == "}" {
            index = source.index(after: index)
        } else {
            while true {
                skipWhitespace()
                let key = try parseString()
                keys.append(key)
                skipWhitespace()
                guard index < source.endIndex, source[index] == ":" else {
                    throw ScreenshotControlContractError.invalidJSON
                }
                index = source.index(after: index)
                try skipValue()
                skipWhitespace()
                guard index < source.endIndex else {
                    throw ScreenshotControlContractError.invalidJSON
                }
                if source[index] == "}" {
                    index = source.index(after: index)
                    break
                }
                guard source[index] == "," else {
                    throw ScreenshotControlContractError.invalidJSON
                }
                index = source.index(after: index)
            }
        }
        skipWhitespace()
        guard index == source.endIndex else {
            throw ScreenshotControlContractError.invalidJSON
        }
        return keys
    }
}
