import Foundation

public protocol ScreenshotAnalyzing {
    func analyze(
        image: PreparedImage,
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL?
    ) async throws -> ScreenshotAnalysis
    func validate(
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL?
    ) async throws
}

public extension ScreenshotAnalyzing {
    func analyze(
        image: PreparedImage,
        apiKey: String,
        model: String,
        provider: AIProvider
    ) async throws -> ScreenshotAnalysis {
        try await analyze(
            image: image,
            apiKey: apiKey,
            model: model,
            provider: provider,
            customEndpoint: nil
        )
    }

    func analyze(
        imageURL: URL,
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL? = nil
    ) async throws -> ScreenshotAnalysis {
        try await analyze(
            image: ImagePreprocessor.prepare(imageURL),
            apiKey: apiKey,
            model: model,
            provider: provider,
            customEndpoint: customEndpoint
        )
    }

    func validate(
        apiKey: String,
        model: String,
        provider: AIProvider
    ) async throws {
        try await validate(
            apiKey: apiKey,
            model: model,
            provider: provider,
            customEndpoint: nil
        )
    }
}

public enum OpenAIClientError: LocalizedError {
    case missingAPIKey
    case unreadableImage
    case invalidResponse
    case api(statusCode: Int, message: String)
    case malformedAnalysis
    case invalidEndpoint

    public var errorDescription: String? {
        switch self {
        case .missingAPIKey:
            return "尚未配置 AI Provider 的 API Key"
        case .unreadableImage:
            return "无法读取截图文件"
        case .invalidResponse:
            return "AI 服务返回了无法识别的响应"
        case let .api(statusCode, message):
            return "AI 请求失败（\(statusCode)）：\(message)"
        case .malformedAnalysis:
            return "AI 没有返回有效的命名结果"
        case .invalidEndpoint:
            return "自定义 API 地址无效，只允许不含账号信息的 HTTPS 地址"
        }
    }

    public var isRetryable: Bool {
        switch self {
        case let .api(statusCode, message):
            let lowercased = message.lowercased()
            if lowercased.contains("no credits") || lowercased.contains("insufficient_quota") {
                return false
            }
            return statusCode == 408 || statusCode == 409 || statusCode == 429 || statusCode >= 500
        case .missingAPIKey, .unreadableImage, .invalidResponse, .malformedAnalysis,
             .invalidEndpoint:
            return false
        }
    }
}

public final class OpenAIClient: ScreenshotAnalyzing {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func analyze(
        image: PreparedImage,
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL? = nil
    ) async throws -> ScreenshotAnalysis {
        guard !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw OpenAIClientError.missingAPIKey
        }
        let imageURLValue = "data:\(image.mimeType);base64,\(image.data.base64EncodedString())"
        let prompt = """
        你是一个截图整理助手。理解截图的核心内容，为 macOS 文件生成简短、清楚、可搜索的中文名称。

        只返回一个 JSON 对象，不要使用 Markdown，不要解释。字段必须是：
        - title：8到24个汉字为宜，不含日期、扩展名、斜杠或冒号；描述具体内容，不要只写“截图”
        - summary：一到两句中文摘要
        - category：只能是 聊天、网页、代码、文档、报错、图片、数据、其他 之一
        - confidence：0到1的小数
        - sensitive：截图是否明显包含身份证号、银行卡、密码、密钥、病历或其他敏感信息

        示例：{"title":"微信聊天-讨论项目报价","summary":"双方讨论项目报价和交付时间。","category":"聊天","confidence":0.95,"sensitive":false}
        """

        let endpoint: URL
        let payload: [String: Any]

        switch provider {
        case .openAI:
            endpoint = URL(string: "https://api.openai.com/v1/responses")!
            payload = [
                "model": model,
                "store": false,
                "max_output_tokens": 260,
                "input": [[
                    "role": "user",
                    "content": [
                        ["type": "input_text", "text": prompt],
                        ["type": "input_image", "image_url": imageURLValue, "detail": "auto"]
                    ]
                ]]
            ]
        case .openRouter, .alibabaBailian, .customOpenAICompatible:
            if provider == .openRouter {
                endpoint = URL(string: "https://openrouter.ai/api/v1/chat/completions")!
            } else if provider == .alibabaBailian {
                endpoint = URL(string: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")!
            } else {
                guard let customEndpoint,
                      CustomProviderEndpoint.validated(customEndpoint.absoluteString) != nil else {
                    throw OpenAIClientError.invalidEndpoint
                }
                endpoint = customEndpoint
            }

            var chatPayload: [String: Any] = [
                "model": model,
                "max_tokens": 260,
                "temperature": 0.1,
                "response_format": ["type": "json_object"],
                "messages": [[
                    "role": "user",
                    "content": [
                        ["type": "text", "text": prompt],
                        ["type": "image_url", "image_url": ["url": imageURLValue]]
                    ]
                ]]
            ]
            if provider == .openRouter {
                chatPayload["provider"] = ["data_collection": "deny"]
            }
            payload = chatPayload
        }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 90
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if provider == .openRouter {
            request.setValue("Froganize Screenshot Intelligence", forHTTPHeaderField: "X-OpenRouter-Title")
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let data = try await executeWithRetry(request)

        return provider == .openAI
            ? try Self.parseAnalysisResponse(data)
            : try Self.parseChatCompletionResponse(data)
    }

    public func validate(
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL? = nil
    ) async throws {
        guard !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw OpenAIClientError.missingAPIKey
        }
        let endpoint: URL
        let payload: [String: Any]

        switch provider {
        case .openAI:
            endpoint = URL(string: "https://api.openai.com/v1/responses")!
            payload = [
                "model": model,
                "store": false,
                "max_output_tokens": 4,
                "input": "只回复 OK"
            ]
        case .openRouter, .alibabaBailian, .customOpenAICompatible:
            if provider == .openRouter {
                endpoint = URL(string: "https://openrouter.ai/api/v1/chat/completions")!
            } else if provider == .alibabaBailian {
                endpoint = URL(string: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")!
            } else {
                guard let customEndpoint,
                      CustomProviderEndpoint.validated(customEndpoint.absoluteString) != nil else {
                    throw OpenAIClientError.invalidEndpoint
                }
                endpoint = customEndpoint
            }
            payload = [
                "model": model,
                "max_tokens": 4,
                "messages": [["role": "user", "content": "只回复 OK"]]
            ]
        }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 45
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if provider == .openRouter {
            request.setValue("Froganize Screenshot Intelligence", forHTTPHeaderField: "X-OpenRouter-Title")
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        _ = try await executeWithRetry(request)
    }

    public static func parseAnalysisResponse(_ data: Data) throws -> ScreenshotAnalysis {
        guard
            let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let output = root["output"] as? [[String: Any]]
        else {
            throw OpenAIClientError.invalidResponse
        }

        let text = output.lazy.compactMap { item -> String? in
            guard let content = item["content"] as? [[String: Any]] else { return nil }
            return content.first(where: { $0["type"] as? String == "output_text" })?["text"] as? String
        }.first

        guard let text, let jsonData = extractJSONObjectData(from: text) else {
            throw OpenAIClientError.malformedAnalysis
        }

        do {
            return try JSONDecoder().decode(ScreenshotAnalysis.self, from: jsonData)
        } catch {
            throw OpenAIClientError.malformedAnalysis
        }
    }

    public static func parseChatCompletionResponse(_ data: Data) throws -> ScreenshotAnalysis {
        guard
            let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let choices = root["choices"] as? [[String: Any]],
            let message = choices.first?["message"] as? [String: Any],
            let text = message["content"] as? String,
            let jsonData = extractJSONObjectData(from: text)
        else {
            throw OpenAIClientError.invalidResponse
        }

        do {
            return try JSONDecoder().decode(ScreenshotAnalysis.self, from: jsonData)
        } catch {
            throw OpenAIClientError.malformedAnalysis
        }
    }

    private static func extractJSONObjectData(from text: String) -> Data? {
        guard let first = text.firstIndex(of: "{"), let last = text.lastIndex(of: "}"), first <= last else {
            return nil
        }
        return String(text[first...last]).data(using: .utf8)
    }

    private func executeWithRetry(_ request: URLRequest) async throws -> Data {
        var lastError: Error?
        let delays: [UInt64] = [0, 1_000_000_000, 2_500_000_000]

        for delay in delays {
            if delay > 0 {
                try? await Task.sleep(nanoseconds: delay)
            }

            do {
                let (data, response) = try await session.data(for: request)
                guard let httpResponse = response as? HTTPURLResponse else {
                    throw OpenAIClientError.invalidResponse
                }
                guard (200..<300).contains(httpResponse.statusCode) else {
                    let message = Self.extractAPIError(from: data)
                        ?? HTTPURLResponse.localizedString(forStatusCode: httpResponse.statusCode)
                    throw OpenAIClientError.api(statusCode: httpResponse.statusCode, message: message)
                }
                return data
            } catch {
                lastError = error
                guard Self.isRetryable(error) else { throw error }
            }
        }

        throw lastError ?? OpenAIClientError.invalidResponse
    }

    public static func isRetryable(_ error: Error) -> Bool {
        if let apiError = error as? OpenAIClientError {
            return apiError.isRetryable
        }
        if let urlError = error as? URLError {
            return [.timedOut, .networkConnectionLost, .notConnectedToInternet, .cannotFindHost, .cannotConnectToHost]
                .contains(urlError.code)
        }
        return false
    }

    private static func extractAPIError(from data: Data) -> String? {
        guard
            let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let error = root["error"] as? [String: Any]
        else { return nil }
        return error["message"] as? String
    }

}
