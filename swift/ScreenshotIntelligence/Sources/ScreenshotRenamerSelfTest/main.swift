import Foundation
import ScreenshotRenamerCore

enum SelfTestError: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case let .failed(message): return message
        }
    }
}

@main
enum ScreenshotRenamerSelfTest {
    static func main() async throws {
        var passed = 0

        try check(
            FilenameSanitizer.sanitize("  微信聊天：项目/报价？.png  ") == "微信聊天-项目-报价",
            "文件名非法字符清理"
        )
        passed += 1

        try check(
            FilenameSanitizer.sanitize(String(repeating: "测试", count: 30), maxLength: 10).count == 10,
            "文件名长度限制"
        )
        passed += 1

        let original = URL(fileURLWithPath: "/tmp/截屏2026.png")
        var conflictChecks = 0
        let destination = FilenameSanitizer.destinationURL(
            for: original,
            title: "项目报价",
            date: Date(timeIntervalSince1970: 0),
            fileExists: { _ in
                defer { conflictChecks += 1 }
                return conflictChecks == 0
            }
        )
        try check(destination.lastPathComponent.hasSuffix("-2.png"), "重名冲突处理")
        passed += 1

        try check(
            ScreenshotDetector.looksLikeScreenshot(URL(fileURLWithPath: "/tmp/截屏2026-08-06 10.00.00.png")),
            "中文系统截图识别"
        )
        try check(
            ScreenshotDetector.looksLikeScreenshot(URL(fileURLWithPath: "/tmp/Screenshot 2026-08-06 at 10.00.00.png")),
            "英文系统截图识别"
        )
        try check(
            !ScreenshotDetector.looksLikeScreenshot(URL(fileURLWithPath: "/tmp/photo.png")),
            "普通图片排除"
        )
        passed += 3

        let response: [String: Any] = [
            "output": [[
                "type": "message",
                "content": [[
                    "type": "output_text",
                    "text": "```json\n{\"title\":\"项目报价讨论\",\"summary\":\"讨论报价。\",\"category\":\"聊天\",\"confidence\":0.9,\"sensitive\":false}\n```"
                ]]
            ]]
        ]
        let data = try JSONSerialization.data(withJSONObject: response)
        let analysis = try OpenAIClient.parseAnalysisResponse(data)
        try check(analysis.title == "项目报价讨论" && analysis.confidence == 0.9, "Responses API 结果解析")
        passed += 1

        let chatResponse: [String: Any] = [
            "choices": [[
                "message": [
                    "content": "{\"title\":\"网页产品说明\",\"summary\":\"介绍产品功能。\",\"category\":\"网页\",\"confidence\":0.88,\"sensitive\":false}"
                ]
            ]]
        ]
        let chatData = try JSONSerialization.data(withJSONObject: chatResponse)
        let chatAnalysis = try OpenAIClient.parseChatCompletionResponse(chatData)
        try check(chatAnalysis.title == "网页产品说明" && chatAnalysis.category == "网页", "兼容接口结果解析")
        passed += 1

        do {
            _ = try OpenAIClient.parseAnalysisResponse(Data("{}".utf8))
            throw SelfTestError.failed("Self-test failed: 无效 AI 响应（did not throw）")
        } catch OpenAIClientError.invalidResponse {
            passed += 1
        }

        try check(
            !OpenAIClientError.api(statusCode: 401, message: "unauthorized").isRetryable,
            "AI 鉴权失败不重试"
        )
        passed += 1

        try check(
            OpenAIClient.isRetryable(URLError(.notConnectedToInternet)),
            "网络失败可安全重试"
        )
        passed += 1

        do {
            try await OpenAIClient().validate(apiKey: "  ", model: "fixture", provider: .openAI)
            throw SelfTestError.failed("Self-test failed: 缺少 API Key（did not throw）")
        } catch OpenAIClientError.missingAPIKey {
            passed += 1
        }

        let credentialAnalyzer = CountingAnalyzer()
        var persistedCredential = ""
        CredentialAction.save(String(repeating: "k", count: 24)) { key in
            persistedCredential = key
        }
        try check(
            persistedCredential.count == 24
                && credentialAnalyzer.validationCallCount == 0,
            "保存 API Key 只持久化且不连接 Provider"
        )
        passed += 1

        try await CredentialAction.testConnection(
            apiKey: persistedCredential,
            model: AIProvider.openAI.defaultModel,
            provider: .openAI,
            analyzer: credentialAnalyzer
        )
        try check(
            credentialAnalyzer.validationCallCount == 1,
            "只有明确测试连接才请求 Provider"
        )
        passed += 1

        let controlRequestID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        let stateControlRequest = try ScreenshotControlContract.decodeRequest(Data(
            "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"get_state\"}".utf8
        ))
        try check(
            stateControlRequest.action == .getState
                && stateControlRequest.requestID.uuidString.lowercased() == controlRequestID,
            "control v1 get_state 解码"
        )
        passed += 1

        let enableControlRequest = try ScreenshotControlContract.decodeRequest(Data(
            "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"set_enabled\",\"enabled\":true,\"consent_version\":1}".utf8
        ))
        let disableControlRequest = try ScreenshotControlContract.decodeRequest(Data(
            "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"set_enabled\",\"enabled\":false,\"consent_version\":0}".utf8
        ))
        try check(
            enableControlRequest.enabled == true
                && enableControlRequest.consentVersion == 1
                && disableControlRequest.enabled == false
                && disableControlRequest.consentVersion == 0,
            "control v1 开启与撤回同意组合"
        )
        passed += 1

        try expectControlError(.duplicateField("action"), "control 拒绝重复字段") {
            _ = try ScreenshotControlContract.decodeRequest(Data(
                "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"get_state\",\"action\":\"undo_latest\"}".utf8
            ))
        }
        passed += 1

        try expectControlError(.unknownField("api_key"), "control get_state 拒绝多余 key 字段") {
            _ = try ScreenshotControlContract.decodeRequest(Data(
                "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"get_state\",\"api_key\":\"must-not-be-accepted-here\"}".utf8
            ))
        }
        passed += 1

        try expectControlError(.invalidRequestID, "control 拒绝非小写 UUID") {
            _ = try ScreenshotControlContract.decodeRequest(Data(
                "{\"schema_version\":1,\"request_id\":\"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA\",\"action\":\"get_state\"}".utf8
            ))
        }
        passed += 1

        try expectControlError(.invalidModel, "control 拒绝 provider/model 越权组合") {
            _ = try ScreenshotControlContract.decodeRequest(Data(
                "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"set_provider_model\",\"provider\":\"openAI\",\"model\":\"qwen/qwen3.7-flash\"}".utf8
            ))
        }
        passed += 1

        let customProviderRequest = try ScreenshotControlContract.decodeRequest(Data(
            "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"configure_custom_provider\",\"endpoint\":\"https://example.com/v1/chat/completions\",\"model\":\"vision-model\"}".utf8
        ))
        try check(
            customProviderRequest.provider == .customOpenAICompatible
                && customProviderRequest.endpoint == "https://example.com/v1/chat/completions"
                && customProviderRequest.model == "vision-model",
            "control 接受 HTTPS 自定义兼容 API"
        )
        passed += 1

        try expectControlError(.invalidField("endpoint"), "control 拒绝非 HTTPS 自定义 API") {
            _ = try ScreenshotControlContract.decodeRequest(Data(
                "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"configure_custom_provider\",\"endpoint\":\"http://example.com/v1/chat/completions\",\"model\":\"vision-model\"}".utf8
            ))
        }
        passed += 1

        try expectControlError(.invalidField("consent_version"), "control 拒绝关闭但保留同意") {
            _ = try ScreenshotControlContract.decodeRequest(Data(
                "{\"schema_version\":1,\"request_id\":\"\(controlRequestID)\",\"action\":\"set_enabled\",\"enabled\":false,\"consent_version\":1}".utf8
            ))
        }
        passed += 1

        try expectControlError(.requestTooLarge, "control 64 KiB 限制") {
            _ = try ScreenshotControlContract.decodeRequest(
                Data(repeating: 0x20, count: ScreenshotControlContract.maximumRequestBytes + 1)
            )
        }
        passed += 1

        let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")!
        let imageURL = FileManager.default.temporaryDirectory.appendingPathComponent("screenshot-renamer-self-test-\(UUID().uuidString).png")
        try png.write(to: imageURL)
        defer { try? FileManager.default.removeItem(at: imageURL) }
        let prepared = try ImagePreprocessor.prepare(imageURL)
        try check(prepared.mimeType == "image/jpeg" && !prepared.data.isEmpty, "截图压缩")
        passed += 1

        try check(
            ScreenshotExecutableMode.parse(arguments: []) == .graphicalApplication
                && ScreenshotExecutableMode.parse(arguments: ["--control"]) == .control
                && ScreenshotExecutableMode.parse(arguments: ["--bogus"]) == .invalid,
            "可执行入口拒绝未知参数"
        )
        passed += 1

        let secureRoot = URL(fileURLWithPath: "/private/tmp", isDirectory: true).appendingPathComponent(
            "froganize-secure-input-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: secureRoot, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: secureRoot) }
        let directScreenshot = secureRoot.appendingPathComponent("Screenshot 2026-08-13 at 10.00.00.png")
        try png.write(to: directScreenshot)
        let directPinned = try SecureScreenshotFile.open(
            root: secureRoot,
            candidate: directScreenshot
        )
        let directPrepared = try directPinned.prepareForUpload()
        let countingAnalyzer = CountingAnalyzer()
        _ = try await countingAnalyzer.analyze(
            image: directPrepared.image,
            apiKey: String(repeating: "x", count: 24),
            model: AIProvider.openAI.defaultModel,
            provider: .openAI
        )
        try check(
            countingAnalyzer.callCount == 1 && directPrepared.snapshot.size == Int64(png.count),
            "普通 direct-child 截图固定读取后才调用 analyzer"
        )
        passed += 1

        let symlinkRoot = secureRoot.deletingLastPathComponent().appendingPathComponent(
            "froganize-secure-root-link-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createSymbolicLink(at: symlinkRoot, withDestinationURL: secureRoot)
        defer { try? FileManager.default.removeItem(at: symlinkRoot) }
        try expectSecureInputFailure("根目录符号链接在 analyzer 前拒绝") {
            let pinned = try SecureScreenshotFile.open(
                root: symlinkRoot,
                candidate: symlinkRoot.appendingPathComponent(directScreenshot.lastPathComponent)
            )
            _ = try pinned.prepareForUpload()
        }
        try check(countingAnalyzer.callCount == 1, "根目录符号链接零 analyzer 调用")
        passed += 2

        let realParent = secureRoot.appendingPathComponent("real-parent", isDirectory: true)
        try FileManager.default.createDirectory(at: realParent, withIntermediateDirectories: true)
        let parentScreenshot = realParent.appendingPathComponent("Screenshot 2026-08-13 at 10.01.00.png")
        try png.write(to: parentScreenshot)
        let parentLink = secureRoot.appendingPathComponent("parent-link", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: parentLink, withDestinationURL: realParent)
        try expectSecureInputFailure("父路径符号链接在 analyzer 前拒绝") {
            _ = try SecureScreenshotFile.open(
                root: parentLink,
                candidate: parentLink.appendingPathComponent(parentScreenshot.lastPathComponent)
            )
        }
        try check(countingAnalyzer.callCount == 1, "父路径符号链接零 analyzer 调用")
        passed += 2

        let leafTarget = secureRoot.appendingPathComponent("leaf-target.png")
        try png.write(to: leafTarget)
        let leafLink = secureRoot.appendingPathComponent("Screenshot 2026-08-13 at 10.02.00.png")
        try FileManager.default.createSymbolicLink(at: leafLink, withDestinationURL: leafTarget)
        try expectSecureInputFailure("叶子符号链接在 analyzer 前拒绝") {
            _ = try SecureScreenshotFile.open(root: secureRoot, candidate: leafLink)
        }
        try check(countingAnalyzer.callCount == 1, "叶子符号链接零 analyzer 调用")
        passed += 2

        let replaced = secureRoot.appendingPathComponent("Screenshot 2026-08-13 at 10.03.00.png")
        try png.write(to: replaced)
        let replacedPinned = try SecureScreenshotFile.open(root: secureRoot, candidate: replaced)
        let displaced = secureRoot.appendingPathComponent("displaced.png")
        try FileManager.default.moveItem(at: replaced, to: displaced)
        try png.write(to: replaced)
        try expectSecureInputFailure("叶子替换在 analyzer 前拒绝") {
            _ = try replacedPinned.prepareForUpload()
        }
        try check(countingAnalyzer.callCount == 1, "叶子替换零 analyzer 调用")
        passed += 2

        let modified = secureRoot.appendingPathComponent("Screenshot 2026-08-13 at 10.04.00.png")
        try png.write(to: modified)
        let modifiedPinned = try SecureScreenshotFile.open(root: secureRoot, candidate: modified)
        try Data([0]).append(to: modified)
        try expectSecureInputFailure("打开后修改在 analyzer 前拒绝") {
            _ = try modifiedPinned.prepareForUpload()
        }
        try check(countingAnalyzer.callCount == 1, "处理中修改零 analyzer 调用")
        passed += 2

        try check(
            SecureScreenshotFileError.fileChanged.isTransientDuringWrite
                && SecureScreenshotFileError.emptyFile.isTransientDuringWrite
                && !SecureScreenshotFileError.unreadable.isTransientDuringWrite
                && !SecureScreenshotFileError.symbolicLink.isTransientDuringWrite,
            "只有常见写入中状态进入有限重试"
        )
        passed += 1

        let changingDuringWindow = secureRoot.appendingPathComponent(
            "Screenshot 2026-08-13 at 10.05.00.png"
        )
        try png.write(to: changingDuringWindow)
        let changingPinned = try SecureScreenshotFile.open(
            root: secureRoot,
            candidate: changingDuringWindow
        )
        let mutation = Task {
            try await Task.sleep(nanoseconds: 20_000_000)
            try Data([0]).append(to: changingDuringWindow)
        }
        do {
            _ = try await changingPinned.prepareForUploadAfterStabilityWindow(
                nanoseconds: 80_000_000
            )
            throw SelfTestError.failed(
                "Self-test failed: 稳定窗口捕获写入中变化（did not throw）"
            )
        } catch SecureScreenshotFileError.fileChanged {
            try await mutation.value
            try check(countingAnalyzer.callCount == 1, "稳定窗口失败零 analyzer 调用")
            passed += 1
        }

        let configureID = UUID(uuidString: "11111111-1111-1111-1111-111111111111")!
        let configureRequest = FileOperationRequest.configureScreenshotRoot(
            URL(fileURLWithPath: "/tmp/蛙仔 截图", isDirectory: true),
            requestID: configureID
        )
        let configureObject = try jsonObject(FileOperationContract.encode(configureRequest))
        try check(
            configureObject["action"] as? String == "configure_screenshot_root"
                && configureObject["source_root"] as? String == "/tmp/蛙仔 截图"
                && configureObject["screenshot_root"] == nil,
            "配置协议字段与 Unicode"
        )
        passed += 1

        let operationID = UUID(uuidString: "22222222-2222-2222-2222-222222222222")!
        let snapshot = FileSnapshot(
            device: 17,
            inode: 42,
            mode: 33_188,
            size: 8_192,
            modificationTimeNanoseconds: 1_786_501_234_567_890_000
        )
        let unicodeAnalysis = ScreenshotAnalysis(
            title: "蛙仔整理项目进度",
            summary: "这是一张包含中文与 emoji 🐸 的截图。",
            category: "文档",
            confidence: 0.94,
            sensitive: false
        )
        let renameRequest = try FileOperationRequest.renameScreenshot(
            sourceName: "截屏2026-08-12 10.20.30.png",
            snapshot: snapshot,
            analysis: unicodeAnalysis,
            provider: "openRouter",
            model: "模型-vision",
            requestID: operationID
        )
        let renameObject = try jsonObject(FileOperationContract.encode(renameRequest))
        let encodedAnalysis = renameObject["analysis"] as? [String: Any]
        let encodedSnapshot = renameObject["snapshot"] as? [String: Any]
        try check(
            renameObject["source_name"] as? String == "截屏2026-08-12 10.20.30.png"
                && encodedAnalysis?["title"] as? String == "蛙仔整理项目进度"
                && encodedSnapshot?["mtime_ns"] as? NSNumber
                    == NSNumber(value: 1_786_501_234_567_890_000 as Int64)
                && renameObject["source_root"] == nil,
            "重命名协议编码与最小路径权限"
        )
        passed += 1

        let renameResponse = try JSONSerialization.data(withJSONObject: [
            "schema_version": 1,
            "request_id": operationID.uuidString.lowercased(),
            "status": "renamed",
            "event_id": "33333333-3333-3333-3333-333333333333",
            "original_name": "截屏2026-08-12 10.20.30.png",
            "renamed_name": "蛙仔整理项目进度-20260812-102030.png"
        ])
        let decodedRename = try FileOperationContract.decodeResponse(
            renameResponse,
            expecting: renameRequest
        )
        try check(
            decodedRename.renamedName == "蛙仔整理项目进度-20260812-102030.png",
            "Unicode 成功响应解码"
        )
        passed += 1

        let mismatchedResponse = try JSONSerialization.data(withJSONObject: [
            "schema_version": 1,
            "request_id": "44444444-4444-4444-4444-444444444444",
            "status": "configured",
            "screenshot_root": "/tmp/蛙仔 截图"
        ])
        try expectBrokerError(.mismatchedRequestID, "拒绝不匹配的 request_id") {
            _ = try FileOperationContract.decodeResponse(
                mismatchedResponse,
                expecting: configureRequest
            )
        }
        passed += 1

        let errorResponse = try JSONSerialization.data(withJSONObject: [
            "schema_version": 1,
            "request_id": NSNull(),
            "status": "error",
            "error": [
                "code": "source_root_missing",
                "message": "选择的截图文件夹不存在",
                "retryable": false
            ]
        ])
        try expectBrokerError(
            .helperRejected(code: "source_root_missing", message: "选择的截图文件夹不存在"),
            "helper 错误响应"
        ) {
            _ = try FileOperationContract.decodeResponse(errorResponse, expecting: configureRequest)
        }
        passed += 1

        let skippedUndoRequest = FileOperationRequest.undoScreenshotRename(
            requestID: UUID(uuidString: "55555555-5555-5555-5555-555555555555")!
        )
        let skippedUndoResponse = try JSONSerialization.data(withJSONObject: [
            "schema_version": 1,
            "request_id": skippedUndoRequest.requestID.uuidString.lowercased(),
            "status": "skipped",
            "reason_code": "nothing_to_undo",
            "reason": "There is no outstanding screenshot rename to undo."
        ])
        let decodedSkip = try FileOperationContract.decodeResponse(
            skippedUndoResponse,
            expecting: skippedUndoRequest
        )
        try check(decodedSkip.reasonCode == "nothing_to_undo", "安全跳过响应")
        passed += 1

        try expectBrokerError(.invalidSourceName, "拒绝路径穿越文件名") {
            _ = try FileOperationRequest.renameScreenshot(
                sourceName: "../截屏.png",
                snapshot: snapshot,
                analysis: unicodeAnalysis,
                provider: "openRouter",
                model: "vision"
            )
        }
        passed += 1

        let relativeHelper = FileOperationBrokerClient(
            environment: [FileOperationBrokerClient.helperEnvironmentVariable: "bin/helper"],
            bundleURL: URL(fileURLWithPath: "/tmp/FroganizeAgent.app")
        )
        try expectBrokerError(.helperPathMustBeAbsolute, "helper 覆盖路径必须绝对") {
            _ = try relativeHelper.resolvedExecutableURL()
        }
        passed += 1

        let bundleTestRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("froganize-bundle-self-test-\(UUID().uuidString)", isDirectory: true)
        let outerContents = bundleTestRoot
            .appendingPathComponent("Froganize.app/Contents", isDirectory: true)
        let nestedBundle = outerContents
            .appendingPathComponent("Library/LoginItems/FroganizeScreenshotAgent.app", isDirectory: true)
        let bundledHelper = outerContents.appendingPathComponent("MacOS/FroganizeFileOps")
        try FileManager.default.createDirectory(
            at: bundledHelper.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(at: nestedBundle, withIntermediateDirectories: true)
        try Data("test helper".utf8).write(to: bundledHelper)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: bundledHelper.path)
        defer { try? FileManager.default.removeItem(at: bundleTestRoot) }
        let bundledClient = FileOperationBrokerClient(environment: [:], bundleURL: nestedBundle)
        let resolvedBundledHelper = try bundledClient.resolvedExecutableURL().standardizedFileURL
        try check(
            resolvedBundledHelper == bundledHelper.standardizedFileURL,
            "固定外层 bundle helper 路径"
        )
        passed += 1

        let sourceSnapshot = try FileSnapshot.capture(imageURL)
        try check(sourceSnapshot.size > 0 && sourceSnapshot.mode > 0, "文件状态快照")
        passed += 1

        let symlinkURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("screenshot-renamer-self-test-link-\(UUID().uuidString).png")
        try FileManager.default.createSymbolicLink(at: symlinkURL, withDestinationURL: imageURL)
        defer { try? FileManager.default.removeItem(at: symlinkURL) }
        try expectBrokerError(.sourceIsNotRegularFile, "符号链接在上传前被拒绝") {
            _ = try FileSnapshot.capture(symlinkURL)
        }
        passed += 1

        let fakeSuccessHelper = try makeExecutable(
            """
            #!/bin/sh
            IFS= read -r request
            printf '%s\\n' '{"schema_version":1,"request_id":"\(configureID.uuidString.lowercased())","status":"configured","screenshot_root":"/tmp/蛙仔 截图"}'
            """
        )
        defer { try? FileManager.default.removeItem(at: fakeSuccessHelper) }
        let fakeSuccessClient = FileOperationBrokerClient(
            executableURL: fakeSuccessHelper,
            timeout: 2
        )
        let processResponse = try await fakeSuccessClient.execute(configureRequest)
        try check(
            processResponse.status == "configured"
                && processResponse.screenshotRoot == "/tmp/蛙仔 截图",
            "Process JSON stdin/stdout"
        )
        passed += 1

        let fakeCrashHelper = try makeExecutable("#!/bin/sh\nexit 7\n")
        defer { try? FileManager.default.removeItem(at: fakeCrashHelper) }
        let fakeCrashClient = FileOperationBrokerClient(executableURL: fakeCrashHelper, timeout: 2)
        try await expectBrokerErrorAsync("helper 非零退出", operation: {
            _ = try await fakeCrashClient.execute(configureRequest)
        }, matches: { error in
            if case .helperExited(code: 7, diagnostic: _) = error { return true }
            return false
        })
        passed += 1

        let fakeSlowHelper = try makeExecutable("#!/bin/sh\nsleep 2\n")
        defer { try? FileManager.default.removeItem(at: fakeSlowHelper) }
        let fakeSlowClient = FileOperationBrokerClient(executableURL: fakeSlowHelper, timeout: 0.05)
        try await expectBrokerErrorAsync("helper 超时", operation: {
            _ = try await fakeSlowClient.execute(configureRequest)
        }, matches: { $0 == .timedOut })
        passed += 1

        let fakeNoisyHelper = try makeExecutable(
            """
            #!/bin/sh
            yes x | head -c 70000
            """
        )
        defer { try? FileManager.default.removeItem(at: fakeNoisyHelper) }
        let fakeNoisyClient = FileOperationBrokerClient(executableURL: fakeNoisyHelper, timeout: 3)
        try await expectBrokerErrorAsync("helper stdout 有界并发读取", operation: {
            _ = try await fakeNoisyClient.execute(configureRequest)
        }, matches: { $0 == .responseTooLarge })
        passed += 1

        let fakeNoisyStderrHelper = try makeExecutable(
            """
            #!/bin/sh
            yes diagnostic >&2 &
            noise=$!
            sleep 0.1
            kill "$noise" 2>/dev/null || true
            printf '%s\\n' '{"schema_version":1,"request_id":"\(configureID.uuidString.lowercased())","status":"configured","screenshot_root":"/tmp/蛙仔 截图"}'
            """
        )
        defer { try? FileManager.default.removeItem(at: fakeNoisyStderrHelper) }
        let fakeNoisyStderrClient = FileOperationBrokerClient(
            executableURL: fakeNoisyStderrHelper,
            timeout: 3
        )
        let noisyStderrResponse = try await fakeNoisyStderrClient.execute(configureRequest)
        try check(noisyStderrResponse.status == "configured", "helper stderr 并发读取不死锁")
        passed += 1

        if let helperPath = ProcessInfo.processInfo.environment["FROGANIZE_E2E_HELPER"],
           !helperPath.isEmpty {
            let root = FileManager.default.temporaryDirectory
                .appendingPathComponent(
                    "froganize-swift-python-e2e-\(UUID().uuidString)",
                    isDirectory: true
                )
            let screenshotFolder = root.appendingPathComponent("Screenshots", isDirectory: true)
            let stateFolder = root.appendingPathComponent("State", isDirectory: true)
            try FileManager.default.createDirectory(
                at: screenshotFolder,
                withIntermediateDirectories: true
            )
            defer { try? FileManager.default.removeItem(at: root) }
            let screenshot = screenshotFolder.appendingPathComponent(
                "Screenshot 2026-08-12 at 10.20.30.png"
            )
            try png.write(to: screenshot)
            let realClient = FileOperationBrokerClient(
                executableURL: URL(fileURLWithPath: helperPath),
                timeout: 10,
                processEnvironment: ["FROGANIZE_STATE_DIR": stateFolder.path]
            )
            let configured = try await realClient.configureScreenshotRoot(screenshotFolder)
            try check(configured.status == "configured", "真实 Python helper 配置")
            let realSnapshot = try FileSnapshot.capture(screenshot)
            let renamed = try await realClient.renameScreenshot(
                at: screenshot,
                snapshot: realSnapshot,
                analysis: unicodeAnalysis,
                provider: "self-test",
                model: "fixture"
            )
            guard let renamedName = renamed.renamedName,
                  let eventID = renamed.eventID else {
                throw SelfTestError.failed("Self-test failed: 真实 helper 改名响应")
            }
            let renamedURL = screenshotFolder.appendingPathComponent(renamedName)
            try check(
                !FileManager.default.fileExists(atPath: screenshot.path)
                    && FileManager.default.fileExists(atPath: renamedURL.path),
                "Swift → Python 安全改名"
            )
            let undone = try await realClient.undoScreenshotRename(eventID: eventID)
            try check(
                undone.status == "undone"
                    && FileManager.default.fileExists(atPath: screenshot.path)
                    && !FileManager.default.fileExists(atPath: renamedURL.path),
                "Swift → Python 改名撤销"
            )
            passed += 3
        }

        print("Self-test passed: \(passed) checks")
    }

    private static func check(_ condition: @autoclosure () -> Bool, _ name: String) throws {
        guard condition() else {
            throw SelfTestError.failed("Self-test failed: \(name)")
        }
    }

    private static func jsonObject(_ data: Data) throws -> [String: Any] {
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw SelfTestError.failed("Self-test failed: JSON object decoding")
        }
        return value
    }

    private static func expectBrokerError(
        _ expected: FileOperationBrokerError,
        _ name: String,
        operation: () throws -> Void
    ) throws {
        do {
            try operation()
        } catch let error as FileOperationBrokerError where error == expected {
            return
        } catch {
            throw SelfTestError.failed("Self-test failed: \(name)（unexpected \(error)）")
        }
        throw SelfTestError.failed("Self-test failed: \(name)（did not throw）")
    }

    private static func expectControlError(
        _ expected: ScreenshotControlContractError,
        _ name: String,
        operation: () throws -> Void
    ) throws {
        do {
            try operation()
        } catch let error as ScreenshotControlContractError where error == expected {
            return
        } catch {
            throw SelfTestError.failed("Self-test failed: \(name)（unexpected \(error)）")
        }
        throw SelfTestError.failed("Self-test failed: \(name)（did not throw）")
    }

    private static func expectSecureInputFailure(
        _ name: String,
        operation: () throws -> Void
    ) throws {
        do {
            try operation()
        } catch is SecureScreenshotFileError {
            return
        } catch {
            throw SelfTestError.failed("Self-test failed: \(name)（unexpected \(error)）")
        }
        throw SelfTestError.failed("Self-test failed: \(name)（did not throw）")
    }

    private static func expectBrokerErrorAsync(
        _ name: String,
        operation: () async throws -> Void,
        matches: (FileOperationBrokerError) -> Bool
    ) async throws {
        do {
            try await operation()
        } catch let error as FileOperationBrokerError where matches(error) {
            return
        } catch {
            throw SelfTestError.failed("Self-test failed: \(name)（unexpected \(error)）")
        }
        throw SelfTestError.failed("Self-test failed: \(name)（did not throw）")
    }

    private static func makeExecutable(_ contents: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("froganize-fake-helper-\(UUID().uuidString)")
        try Data(contents.utf8).write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: url.path)
        return url
    }
}

private final class CountingAnalyzer: ScreenshotAnalyzing, @unchecked Sendable {
    private(set) var callCount = 0
    private(set) var validationCallCount = 0

    func analyze(
        image: PreparedImage,
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL?
    ) async throws -> ScreenshotAnalysis {
        callCount += 1
        return ScreenshotAnalysis(
            title: "安全截图测试",
            summary: "固定文件描述符测试。",
            category: "其他",
            confidence: 0.99,
            sensitive: false
        )
    }

    func validate(
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL?
    ) async throws {
        validationCallCount += 1
    }
}

private extension Data {
    func append(to url: URL) throws {
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.seekToEnd()
        try handle.write(contentsOf: self)
    }
}
