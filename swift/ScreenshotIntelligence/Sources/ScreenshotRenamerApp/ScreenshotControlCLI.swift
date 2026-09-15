import Foundation
import ScreenshotRenamerCore

enum ScreenshotControlCLI {
    static func run() async -> Int32 {
        let input = readBoundedStandardInput()
        let requestID = requestIDFromUntrustedData(input)

        do {
            let request = try ScreenshotControlContract.decodeRequest(input)
            let result = try await handle(request)
            return emit(result, exitCode: 0)
        } catch {
            let safeError = mapError(error)
            let response: [String: Any] = [
                "schema_version": ScreenshotControlContract.schemaVersion,
                "request_id": requestID?.uuidString.lowercased() ?? NSNull(),
                "status": "error",
                "error": [
                    "code": safeError.code,
                    "message": safeError.message,
                    "retryable": safeError.retryable
                ]
            ]
            // A valid correlation ID means the caller can safely consume this
            // as an application-level error. Reserve non-zero exits for input
            // that cannot be correlated to a request.
            return emit(response, exitCode: requestID == nil ? 2 : 0)
        }
    }

    private static func readBoundedStandardInput() -> Data {
        let limit = ScreenshotControlContract.maximumRequestBytes + 1
        var result = Data()
        while result.count < limit {
            let remaining = limit - result.count
            let chunkSize = min(8 * 1_024, remaining)
            guard let chunk = try? FileHandle.standardInput.read(upToCount: chunkSize),
                  !chunk.isEmpty else { break }
            result.append(chunk)
        }
        return result
    }

    private static func handle(_ request: ScreenshotControlRequest) async throws -> [String: Any] {
        let defaults = UserDefaults.standard
        let credentials = CredentialStore()
        let broker = FileOperationBrokerClient()
        var message: String

        switch request.action {
        case .getState:
            message = "已读取截图智能状态"

        case .configureFolder:
            let folder = URL(fileURLWithPath: request.folderPath!, isDirectory: true).standardizedFileURL
            _ = try await broker.configureScreenshotRoot(folder)
            defaults.set(folder.path, forKey: SharedScreenshotConfiguration.folderPathKey)
            defaults.set("截图文件夹已配置", forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()
            message = "截图文件夹已配置"

        case .setProviderModel:
            let provider = request.provider!
            defaults.set(provider.rawValue, forKey: SharedScreenshotConfiguration.providerKey)
            defaults.set(request.model!, forKey: SharedScreenshotConfiguration.modelKey(for: provider))
            if !credentials.hasAPIKey(for: provider) {
                defaults.set(false, forKey: SharedScreenshotConfiguration.enabledKey)
                defaults.set(false, forKey: SharedScreenshotConfiguration.uploadConsentKey)
            }
            defaults.set("AI Provider 与模型已更新", forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()
            message = "AI Provider 与模型已更新"

        case .configureCustomProvider:
            let provider = AIProvider.customOpenAICompatible
            defaults.set(provider.rawValue, forKey: SharedScreenshotConfiguration.providerKey)
            defaults.set(request.endpoint!, forKey: SharedScreenshotConfiguration.customEndpointKey)
            defaults.set(request.model!, forKey: SharedScreenshotConfiguration.customModelKey)
            if !credentials.hasAPIKey(for: provider) {
                defaults.set(false, forKey: SharedScreenshotConfiguration.enabledKey)
                defaults.set(false, forKey: SharedScreenshotConfiguration.uploadConsentKey)
            }
            defaults.set("自定义 API 配置已保存", forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()
            message = "自定义兼容 API 已保存"

        case .setEnabled:
            if request.enabled == true {
                guard request.consentVersion == ScreenshotControlContract.consentVersion else {
                    throw SafeControlError(
                        code: "consent_required",
                        message: "开启前必须确认截图上传说明",
                        retryable: false
                    )
                }
                let provider = SharedScreenshotConfiguration.provider(in: defaults)
                guard credentials.hasAPIKey(for: provider) else {
                    throw SafeControlError(
                        code: "credential_missing",
                        message: "请先为当前 AI Provider 保存 API Key",
                        retryable: false
                    )
                }
                let folder = SharedScreenshotConfiguration.folder(in: defaults)
                _ = try await broker.configureScreenshotRoot(folder)
                defaults.set(true, forKey: SharedScreenshotConfiguration.uploadConsentKey)
                defaults.set(true, forKey: SharedScreenshotConfiguration.enabledKey)
                message = "截图智能已开启"
            } else {
                defaults.set(false, forKey: SharedScreenshotConfiguration.enabledKey)
                defaults.set(false, forKey: SharedScreenshotConfiguration.uploadConsentKey)
                message = "截图智能已关闭"
            }
            defaults.set(message, forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()

        case .saveAPIKey:
            let provider = request.provider!
            try credentials.saveToKeychain(request.apiKey!, for: provider)
            defaults.set("\(provider.displayName) API Key 已安全保存", forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()
            message = "\(provider.displayName) API Key 已安全保存到 macOS 钥匙串"

        case .removeAPIKey:
            let provider = request.provider!
            try credentials.removeFromKeychain(for: provider)
            if provider == SharedScreenshotConfiguration.provider(in: defaults) {
                defaults.set(false, forKey: SharedScreenshotConfiguration.enabledKey)
                defaults.set(false, forKey: SharedScreenshotConfiguration.uploadConsentKey)
            }
            defaults.set("\(provider.displayName) API Key 已移除", forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()
            message = "\(provider.displayName) API Key 已移除"

        case .testConnection:
            let provider = request.provider!
            guard let credential = credentials.loadAPIKey(for: provider) else {
                throw SafeControlError(
                    code: "credential_missing",
                    message: "请先为 \(provider.displayName) 保存 API Key",
                    retryable: false
                )
            }
            try await OpenAIClient().validate(
                apiKey: credential.key,
                model: request.model!,
                provider: provider,
                customEndpoint: provider == .customOpenAICompatible
                    ? SharedScreenshotConfiguration.customEndpoint(in: defaults)
                    : nil
            )
            message = "\(provider.displayName) 连接成功"

        case .processLatest:
            let provider = SharedScreenshotConfiguration.provider(in: defaults)
            let result = try await ScreenshotProcessingService().processLatest(
                folder: SharedScreenshotConfiguration.folder(in: defaults),
                provider: provider,
                model: SharedScreenshotConfiguration.model(for: provider, in: defaults),
                enabled: SharedScreenshotConfiguration.enabled(in: defaults)
            )
            defaults.set(
                result.eventID.uuidString.lowercased(),
                forKey: SharedScreenshotConfiguration.lastRenameEventIDKey
            )
            message = "已重命名：\(result.renamedURL.lastPathComponent)"
            defaults.set(message, forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()

        case .undoLatest:
            let eventID = SharedScreenshotConfiguration.lastRenameEventID(in: defaults)
            let response = try await broker.undoScreenshotRename(eventID: eventID)
            if response.status == "skipped" {
                message = "没有需要撤销的截图重命名"
            } else {
                guard let restoredName = response.restoredName else {
                    throw FileOperationBrokerError.invalidResponse
                }
                message = "已撤销：\(restoredName)"
            }
            defaults.removeObject(forKey: SharedScreenshotConfiguration.lastRenameEventIDKey)
            defaults.set(message, forKey: SharedScreenshotConfiguration.statusMessageKey)
            SharedScreenshotConfiguration.publishChange()
        }

        return [
            "schema_version": ScreenshotControlContract.schemaVersion,
            "request_id": request.requestID.uuidString.lowercased(),
            "status": "ok",
            "message": message,
            "state": stateObject(defaults: defaults, credentials: credentials)
        ]
    }

    private static func stateObject(
        defaults: UserDefaults,
        credentials: CredentialStore
    ) -> [String: Any] {
        let provider = SharedScreenshotConfiguration.provider(in: defaults)
        let credentialSource = credentials.credentialSource(for: provider)
        let customModel = SharedScreenshotConfiguration.customModel(in: defaults)
        let providerOptions: [[String: Any]] = [[
            "id": AIProvider.customOpenAICompatible.rawValue,
            "name": "通用 API",
            "models": [[
                "id": customModel.isEmpty
                    ? AIProvider.customOpenAICompatible.defaultModel
                    : customModel,
                "name": customModel.isEmpty ? "请填写模型名称" : customModel
            ]]
        ]]
        return [
            "enabled": SharedScreenshotConfiguration.enabled(in: defaults),
            "upload_consent": SharedScreenshotConfiguration.uploadConsent(in: defaults),
            "provider": provider.rawValue,
            "model": SharedScreenshotConfiguration.model(for: provider, in: defaults),
            "folder_path": SharedScreenshotConfiguration.folder(in: defaults).path,
            "credential_configured": credentialSource != nil,
            "credential_source": credentialSource?.rawValue ?? NSNull(),
            "provider_options": providerOptions,
            "is_working": ScreenshotProcessingService.isProcessing,
            "status_message": defaults.string(
                forKey: SharedScreenshotConfiguration.statusMessageKey
            ) ?? "准备就绪",
            "last_rename_event_id": SharedScreenshotConfiguration.lastRenameEventID(in: defaults)
                .map { $0.uuidString.lowercased() } ?? NSNull(),
            "custom_endpoint": SharedScreenshotConfiguration.customEndpointString(in: defaults),
            "custom_model": SharedScreenshotConfiguration.customModel(in: defaults)
        ]
    }

    private static func requestIDFromUntrustedData(_ data: Data) -> UUID? {
        guard data.count <= ScreenshotControlContract.maximumRequestBytes,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let value = object["request_id"] as? String,
              let id = UUID(uuidString: value),
              id.uuidString.lowercased() == value else { return nil }
        return id
    }

    private static func emit(_ object: [String: Any], exitCode: Int32) -> Int32 {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys]
              ),
              data.count <= ScreenshotControlContract.maximumResponseBytes else {
            let fallbackObject: [String: Any] = [
                "schema_version": 1,
                "request_id": NSNull(),
                "status": "error",
                "error": [
                    "code": "response_encoding_failed",
                    "message": "无法生成安全响应",
                    "retryable": false
                ]
            ]
            var fallback = (try? JSONSerialization.data(
                withJSONObject: fallbackObject,
                options: [.sortedKeys]
            )) ?? Data("{}".utf8)
            fallback.append(0x0A)
            try? FileHandle.standardOutput.write(contentsOf: fallback)
            return 2
        }
        var output = data
        output.append(0x0A)
        try? FileHandle.standardOutput.write(contentsOf: output)
        return exitCode
    }

    private static func mapError(_ error: Error) -> SafeControlError {
        if let safe = error as? SafeControlError { return safe }
        if let contract = error as? ScreenshotControlContractError {
            return SafeControlError(
                code: contract.code,
                message: contract.localizedDescription,
                retryable: false
            )
        }
        if let processing = error as? ScreenshotProcessingError {
            let retryable: Bool
            let code: String
            switch processing {
            case .alreadyProcessing:
                code = "already_processing"; retryable = true
            case .featureDisabled:
                code = "feature_disabled"; retryable = false
            case .missingCredential:
                code = "credential_missing"; retryable = false
            case .noScreenshot:
                code = "no_screenshot"; retryable = false
            case .lowConfidence:
                code = "low_confidence"; retryable = false
            case .skipped:
                code = "rename_skipped"; retryable = false
            }
            return SafeControlError(
                code: code,
                message: processing.localizedDescription,
                retryable: retryable
            )
        }
        if let secureInput = error as? SecureScreenshotFileError {
            switch secureInput {
            case .fileChanged:
                return SafeControlError(
                    code: "screenshot_changed",
                    message: "截图在上传前发生变化；请刷新后重试",
                    retryable: true
                )
            case .fileTooLarge:
                return SafeControlError(
                    code: "screenshot_too_large",
                    message: "截图超过安全大小限制，未上传",
                    retryable: false
                )
            case .emptyFile:
                return SafeControlError(
                    code: "screenshot_not_stable",
                    message: "截图可能仍在写入；请稍后重试",
                    retryable: true
                )
            case .unreadable:
                return SafeControlError(
                    code: "screenshot_unreadable",
                    message: "无法安全读取截图，未上传",
                    retryable: false
                )
            case .rootMustBeAbsolute, .unsafeRoot, .candidateNotDirectChild,
                 .unsafeCandidateName, .symbolicLink, .notRegularFile:
                return SafeControlError(
                    code: "unsafe_screenshot",
                    message: "截图路径未通过安全检查，未上传",
                    retryable: false
                )
            }
        }
        if let provider = error as? OpenAIClientError {
            switch provider {
            case .missingAPIKey:
                return SafeControlError(code: "credential_missing", message: "尚未保存 API Key", retryable: false)
            case .unreadableImage:
                return SafeControlError(code: "unreadable_image", message: "无法读取截图", retryable: false)
            case .invalidResponse, .malformedAnalysis:
                return SafeControlError(code: "provider_invalid_response", message: "AI 服务返回了无法验证的响应", retryable: false)
            case .invalidEndpoint:
                return SafeControlError(code: "invalid_endpoint", message: provider.localizedDescription, retryable: false)
            case let .api(statusCode, _):
                if statusCode == 401 || statusCode == 403 {
                    return SafeControlError(code: "provider_authentication_failed", message: "API Key 无效或没有访问权限", retryable: false)
                }
                if statusCode == 429 {
                    return SafeControlError(code: "provider_rate_limited", message: "AI 服务请求过于频繁，请稍后再试", retryable: true)
                }
                return SafeControlError(
                    code: "provider_request_failed",
                    message: "AI 服务暂时无法完成请求",
                    retryable: provider.isRetryable
                )
            }
        }
        if let urlError = error as? URLError {
            return SafeControlError(
                code: "network_error",
                message: "无法连接 AI 服务，请检查网络后重试",
                retryable: OpenAIClient.isRetryable(urlError)
            )
        }
        if let broker = error as? FileOperationBrokerError {
            let retryable = broker == .timedOut
            return SafeControlError(
                code: "file_operation_failed",
                message: broker.localizedDescription,
                retryable: retryable
            )
        }
        if error is CredentialStoreError {
            return SafeControlError(
                code: "keychain_error",
                message: "macOS 钥匙串操作失败",
                retryable: false
            )
        }
        return SafeControlError(
            code: "internal_error",
            message: "截图智能无法完成请求",
            retryable: false
        )
    }
}

private struct SafeControlError: Error {
    let code: String
    let message: String
    let retryable: Bool
}
