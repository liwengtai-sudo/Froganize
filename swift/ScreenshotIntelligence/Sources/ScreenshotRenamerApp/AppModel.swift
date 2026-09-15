import AppKit
import Foundation
import ScreenshotRenamerCore

@MainActor
final class AppModel: ObservableObject {
    @Published var isEnabled: Bool {
        didSet {
            guard !isApplyingExternalConfiguration else { return }
            defaults.set(isEnabled, forKey: SharedScreenshotConfiguration.enabledKey)
            if isEnabled {
                defaults.set(true, forKey: SharedScreenshotConfiguration.uploadConsentKey)
            } else {
                defaults.set(false, forKey: SharedScreenshotConfiguration.uploadConsentKey)
            }
            guard hasStarted else { return }
            if isEnabled {
                guard credentials.hasAPIKey(for: provider) else {
                    isEnabled = false
                    status = "请先保存 \(provider.displayName) API Key"
                    return
                }
                Task { await configureSelectedFolderAndStartMonitoring() }
            } else {
                stopMonitoring()
            }
        }
    }

    @Published var provider: AIProvider {
        didSet {
            guard !isApplyingExternalConfiguration else { return }
            defaults.set(provider.rawValue, forKey: SharedScreenshotConfiguration.providerKey)
            modelName = SharedScreenshotConfiguration.model(for: provider, in: defaults)
            if hasStarted {
                refreshCredentialStatus()
                if isEnabled, !credentials.hasAPIKey(for: provider) {
                    isEnabled = false
                    status = "已切换 AI Provider；请保存 API Key 后重新开启"
                }
            }
        }
    }

    @Published var modelName: String {
        didSet {
            guard !isApplyingExternalConfiguration else { return }
            guard provider.supports(model: modelName) else { return }
            let key = provider == .customOpenAICompatible
                ? SharedScreenshotConfiguration.customModelKey
                : SharedScreenshotConfiguration.modelKey(for: provider)
            defaults.set(modelName, forKey: key)
        }
    }

    @Published var customEndpointText: String
    @Published var customModelText: String

    @Published private(set) var selectedFolder: URL
    @Published private(set) var status = "准备就绪"
    @Published private(set) var isWorking = false
    @Published private(set) var credentialDescription = "正在检查 API Key…"
    @Published private(set) var lastRenameEventID: UUID?

    private let defaults = UserDefaults.standard
    private let watcher = FolderWatcher()
    private let analyzer: ScreenshotAnalyzing
    private let broker: FileOperationBrokerClient
    private let credentials: CredentialStore
    private let processor: ScreenshotProcessingService
    private var seenPaths = Set<String>()
    private var hasStarted = false
    private var isScanning = false
    private var scanRequested = false
    private var retryNotBefore: [String: Date] = [:]
    private var retryAttempts: [String: Int] = [:]
    private var retryWakeups = Set<String>()
    private var failedPaths = Set<String>()
    private var isApplyingExternalConfiguration = false
    private var configurationObserver: NSObjectProtocol?

    init(
        analyzer: ScreenshotAnalyzing = OpenAIClient(),
        broker: FileOperationBrokerClient = FileOperationBrokerClient()
    ) {
        let initialProvider = SharedScreenshotConfiguration.provider()
        let credentialStore = CredentialStore()
        self.analyzer = analyzer
        self.broker = broker
        self.credentials = credentialStore
        self.processor = ScreenshotProcessingService(
            analyzer: analyzer,
            broker: broker,
            credentials: credentialStore
        )
        self.isEnabled = SharedScreenshotConfiguration.enabled()
        self.provider = initialProvider
        self.modelName = SharedScreenshotConfiguration.model(for: initialProvider)
        self.customEndpointText = SharedScreenshotConfiguration.customEndpointString()
        self.customModelText = SharedScreenshotConfiguration.customModel()
        self.lastRenameEventID = SharedScreenshotConfiguration.lastRenameEventID()
        self.selectedFolder = SharedScreenshotConfiguration.folder()

        configurationObserver = DistributedNotificationCenter.default().addObserver(
            forName: SharedScreenshotConfiguration.changedNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.reloadExternalConfiguration()
            }
        }
    }

    deinit {
        if let configurationObserver {
            DistributedNotificationCenter.default().removeObserver(configurationObserver)
        }
    }

    var folderPath: String { selectedFolder.path }
    var apiKeyLabel: String { provider.apiKeyLabel }
    var modelOptions: [AIModelOption] {
        if provider == .customOpenAICompatible {
            return [AIModelOption(id: modelName, name: modelName)]
        }
        return provider.models
    }
    var hasSavedCredential: Bool { credentials.hasAPIKey(for: provider) }

    func startIfNeeded() {
        guard !hasStarted else { return }
        hasStarted = true
        refreshCredentialStatus()
        Task { await configureSelectedFolderAndStartMonitoring() }
    }

    func reloadExternalConfiguration() {
        let nextProvider = SharedScreenshotConfiguration.provider(in: defaults)
        isApplyingExternalConfiguration = true
        provider = nextProvider
        modelName = SharedScreenshotConfiguration.model(for: nextProvider, in: defaults)
        customEndpointText = SharedScreenshotConfiguration.customEndpointString(in: defaults)
        customModelText = SharedScreenshotConfiguration.customModel(in: defaults)
        selectedFolder = SharedScreenshotConfiguration.folder(in: defaults)
        isEnabled = SharedScreenshotConfiguration.enabled(in: defaults)
        lastRenameEventID = SharedScreenshotConfiguration.lastRenameEventID(in: defaults)
        isApplyingExternalConfiguration = false
        refreshCredentialStatus()
        if let externalStatus = defaults.string(
            forKey: SharedScreenshotConfiguration.statusMessageKey
        ) {
            status = externalStatus
        }
        guard hasStarted else { return }
        Task { await configureSelectedFolderAndStartMonitoring() }
    }

    func chooseFolder() {
        let panel = NSOpenPanel()
        panel.title = "选择截图保存文件夹"
        panel.prompt = "选择"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = selectedFolder

        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task {
            status = "正在验证截图文件夹…"
            do {
                _ = try await broker.configureScreenshotRoot(url)
                selectedFolder = url.standardizedFileURL
                defaults.set(
                    selectedFolder.path,
                    forKey: SharedScreenshotConfiguration.folderPathKey
                )
                if isEnabled {
                    startMonitoring()
                } else {
                    status = "截图文件夹已准备；截图智能仍为关闭状态"
                }
            } catch {
                status = "无法使用该截图文件夹：\(error.localizedDescription)"
            }
        }
    }

    func scanForNewScreenshots() {
        guard isEnabled else {
            scanRequested = false
            return
        }
        scanRequested = true
        guard !isScanning else { return }
        isScanning = true
        Task {
            await processPendingScreenshots()
            isScanning = false
            if scanRequested { scanForNewScreenshots() }
        }
    }

    func testMostRecentScreenshot() {
        guard isEnabled else {
            status = "请先明确开启截图智能；关闭时不会上传截图"
            return
        }
        guard !isScanning else { return }
        isScanning = true
        Task {
            defer { isScanning = false }
            guard let latest = screenshotURLs().first else {
                status = "该文件夹中没有可识别的系统截图"
                return
            }
            await process(url: latest, isManualTest: true)
        }
    }

    func undoLatest() {
        guard !isWorking else { return }
        isWorking = true
        status = "正在撤销最近一次截图重命名…"
        Task {
            defer { isWorking = false }
            do {
                let response = try await broker.undoScreenshotRename(eventID: lastRenameEventID)
                if response.status == "skipped" {
                    lastRenameEventID = nil
                    defaults.removeObject(
                        forKey: SharedScreenshotConfiguration.lastRenameEventIDKey
                    )
                    status = "没有需要撤销的截图重命名"
                    return
                }
                lastRenameEventID = nil
                defaults.removeObject(
                    forKey: SharedScreenshotConfiguration.lastRenameEventIDKey
                )
                if let restoredName = response.restoredName {
                    status = "已撤销：\(restoredName)"
                } else {
                    status = "已撤销最近一次截图重命名"
                }
            } catch {
                status = "撤销失败：\(error.localizedDescription)"
            }
        }
    }

    func saveAPIKeyToKeychain(_ key: String) {
        do {
            try CredentialAction.save(key) { value in
                try credentials.saveToKeychain(value, for: provider)
            }
            refreshCredentialStatus()
            status = "已安全保存 \(provider.displayName) API Key；尚未连接 AI 服务"
        } catch {
            status = "保存失败：\(error.localizedDescription)"
        }
    }

    func saveCustomProviderConfiguration() {
        guard CustomProviderEndpoint.validated(customEndpointText) != nil else {
            status = "请填写完整的 HTTPS Chat Completions 接口地址"
            return
        }
        guard AIProvider.customOpenAICompatible.supports(model: customModelText) else {
            status = "请填写有效的模型名称"
            return
        }
        defaults.set(customEndpointText, forKey: SharedScreenshotConfiguration.customEndpointKey)
        defaults.set(customModelText, forKey: SharedScreenshotConfiguration.customModelKey)
        provider = .customOpenAICompatible
        modelName = customModelText
        status = "自定义兼容 API 已保存；尚未连接 AI 服务"
    }

    func testConnection() {
        guard !isWorking else { return }
        guard let credential = credentials.loadAPIKey(for: provider) else {
            refreshCredentialStatus()
            status = "请先保存 \(provider.displayName) API Key"
            return
        }
        let testedProvider = provider
        let testedModel = modelName
        isWorking = true
        status = "正在测试 \(testedProvider.displayName) 连接…"
        Task {
            defer { isWorking = false }
            await validateCredential(
                apiKey: credential.key,
                provider: testedProvider,
                model: testedModel
            )
        }
    }

    func removeKeychainAPIKey() {
        do {
            try credentials.removeFromKeychain(for: provider)
            if isEnabled {
                isEnabled = false
            } else {
                defaults.set(false, forKey: SharedScreenshotConfiguration.enabledKey)
                defaults.set(false, forKey: SharedScreenshotConfiguration.uploadConsentKey)
            }
            refreshCredentialStatus()
            status = "已移除 \(provider.displayName) API Key"
        } catch {
            status = "移除失败：\(error.localizedDescription)"
        }
    }

    private func startMonitoring() {
        watcher.stop()
        seenPaths = Set(screenshotURLs().map(\.path))

        do {
            try watcher.start(watching: selectedFolder) { [weak self] in
                Task { @MainActor in
                    self?.scanForNewScreenshots()
                }
            }
            status = "正在监听新截图"
        } catch {
            status = "无法监听文件夹：\(error.localizedDescription)"
        }
    }

    private func stopMonitoring() {
        watcher.stop()
        status = "截图智能已关闭"
    }

    private func configureSelectedFolderAndStartMonitoring() async {
        let folder = selectedFolder
        status = "正在连接 Froganize 文件安全服务…"
        do {
            _ = try await broker.configureScreenshotRoot(folder)
            guard folder == selectedFolder else { return }
            if isEnabled {
                startMonitoring()
            } else {
                status = "截图智能已关闭；不会上传截图"
            }
        } catch {
            if isEnabled {
                isEnabled = false
            }
            status = "文件安全服务不可用：\(error.localizedDescription)"
        }
    }

    private func processPendingScreenshots() async {
        guard isEnabled else {
            scanRequested = false
            return
        }
        guard credentials.hasAPIKey(for: provider) else {
            refreshCredentialStatus()
            status = "缺少 \(provider.displayName) API Key"
            scanRequested = false
            return
        }

        repeat {
            scanRequested = false
            let now = Date()
            let candidates = screenshotURLs()
                .filter { !seenPaths.contains($0.path) }
                .filter { retryNotBefore[$0.path].map { $0 <= now } ?? true }
                .reversed()

            for url in candidates {
                seenPaths.insert(url.path)
                await process(url: url, isManualTest: false)
            }
        } while scanRequested
    }

    private func process(url: URL, isManualTest: Bool) async {
        let activeProvider = provider
        let activeModel = modelName

        isWorking = true
        status = isManualTest ? "正在处理现有截图：\(url.lastPathComponent)" : "正在识别：\(url.lastPathComponent)"
        defer { isWorking = false }

        do {
            let result = try await processor.process(
                url: url,
                folder: selectedFolder,
                provider: activeProvider,
                model: activeModel,
                enabled: isEnabled
            )
            lastRenameEventID = result.eventID
            defaults.set(
                result.eventID.uuidString.lowercased(),
                forKey: SharedScreenshotConfiguration.lastRenameEventIDKey
            )
            let renamedName = result.renamedURL.lastPathComponent
            seenPaths.insert(result.renamedURL.path)
            retryNotBefore.removeValue(forKey: url.path)
            retryAttempts.removeValue(forKey: url.path)
            failedPaths.remove(url.path)
            status = "已重命名：\(renamedName)"
        } catch {
            status = "处理失败：\(error.localizedDescription)"
            guard !isManualTest else { return }

            let shouldRetry = OpenAIClient.isRetryable(error)
                || (error as? SecureScreenshotFileError)?.isTransientDuringWrite == true
                || (error as? ScreenshotProcessingError) == .alreadyProcessing
            if shouldRetry, retryAttempts[url.path, default: 0] < 2 {
                let attempt = retryAttempts[url.path, default: 0] + 1
                retryAttempts[url.path] = attempt
                let delay = TimeInterval(20 * attempt)
                retryNotBefore[url.path] = Date().addingTimeInterval(delay)
                seenPaths.remove(url.path)
                scheduleRetry(for: url.path, after: delay)
            } else {
                failedPaths.insert(url.path)
            }
        }
    }

    private func scheduleRetry(for path: String, after delay: TimeInterval) {
        guard retryWakeups.insert(path).inserted else { return }
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard let self else { return }
            retryWakeups.remove(path)
            scanForNewScreenshots()
        }
    }

    private func validateCredential(apiKey: String, provider: AIProvider, model: String) async {
        do {
            try await CredentialAction.testConnection(
                apiKey: apiKey,
                model: model,
                provider: provider,
                customEndpoint: provider == .customOpenAICompatible
                    ? SharedScreenshotConfiguration.customEndpoint(in: defaults)
                    : nil,
                analyzer: analyzer
            )
            guard self.provider == provider else { return }
            refreshCredentialStatus()
            status = "\(provider.displayName) 连接成功"
            for path in failedPaths { seenPaths.remove(path) }
            failedPaths.removeAll()
            if isEnabled {
                scanForNewScreenshots()
            }
        } catch {
            guard self.provider == provider else { return }
            status = "验证失败：\(error.localizedDescription)"
        }
    }

    private func screenshotURLs() -> [URL] {
        ScreenshotProcessingService.screenshotURLs(in: selectedFolder)
    }

    private func refreshCredentialStatus() {
        if let source = credentials.credentialSource(for: provider) {
            credentialDescription = "已保存（\(source.rawValue)）"
        } else {
            credentialDescription = "未保存"
        }
    }
}
