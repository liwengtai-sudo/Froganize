import Darwin
import Foundation
import ScreenshotRenamerCore

enum ScreenshotProcessingError: LocalizedError, Equatable {
    case alreadyProcessing
    case featureDisabled
    case missingCredential
    case noScreenshot
    case lowConfidence
    case skipped

    var errorDescription: String? {
        switch self {
        case .alreadyProcessing:
            return "另一张截图正在处理，请稍后再试"
        case .featureDisabled:
            return "截图智能尚未开启"
        case .missingCredential:
            return "尚未为当前 AI Provider 保存 API Key"
        case .noScreenshot:
            return "所选文件夹中没有可识别的系统截图"
        case .lowConfidence:
            return "AI 置信度较低，未自动重命名"
        case .skipped:
            return "截图未达到安全自动改名条件"
        }
    }
}

struct ScreenshotProcessingResult: Sendable {
    let eventID: UUID
    let originalURL: URL
    let renamedURL: URL
}

/// Shared by the watcher and `--control`, so both paths use identical upload,
/// confidence and file-operation rules.
final class ScreenshotProcessingService {
    private let analyzer: ScreenshotAnalyzing
    private let broker: FileOperationBrokerClient
    private let credentials: CredentialStore

    init(
        analyzer: ScreenshotAnalyzing = OpenAIClient(),
        broker: FileOperationBrokerClient = FileOperationBrokerClient(),
        credentials: CredentialStore = CredentialStore()
    ) {
        self.analyzer = analyzer
        self.broker = broker
        self.credentials = credentials
    }

    static var isProcessing: Bool {
        ScreenshotProcessingLock.isLocked
    }

    func processLatest(
        folder: URL,
        provider: AIProvider,
        model: String,
        enabled: Bool
    ) async throws -> ScreenshotProcessingResult {
        let context = try validatedContext(
            provider: provider,
            model: model,
            enabled: enabled
        )
        let lock = try ScreenshotProcessingLock.acquire()
        defer { lock.release() }

        // Python authoritatively validates and records the configured root
        // before any local candidate is opened or uploaded.
        _ = try await broker.configureScreenshotRoot(folder)
        guard let latest = Self.screenshotURLs(in: folder).first else {
            throw ScreenshotProcessingError.noScreenshot
        }
        return try await processLocked(
            url: latest,
            folder: folder,
            context: context
        )
    }

    func process(
        url: URL,
        folder: URL,
        provider: AIProvider,
        model: String,
        enabled: Bool
    ) async throws -> ScreenshotProcessingResult {
        let context = try validatedContext(provider: provider, model: model, enabled: enabled)
        let lock = try ScreenshotProcessingLock.acquire()
        defer { lock.release() }

        _ = try await broker.configureScreenshotRoot(folder)
        return try await processLocked(url: url, folder: folder, context: context)
    }

    private func validatedContext(
        provider: AIProvider,
        model: String,
        enabled: Bool
    ) throws -> (provider: AIProvider, model: String, credential: String, endpoint: URL?) {
        guard enabled else { throw ScreenshotProcessingError.featureDisabled }
        guard provider.supports(model: model) else {
            throw ScreenshotControlContractError.invalidModel
        }
        let endpoint = provider == .customOpenAICompatible
            ? SharedScreenshotConfiguration.customEndpoint()
            : nil
        if provider == .customOpenAICompatible, endpoint == nil {
            throw OpenAIClientError.invalidEndpoint
        }
        guard let credential = credentials.loadAPIKey(for: provider) else {
            throw ScreenshotProcessingError.missingCredential
        }
        return (provider, model, credential.key, endpoint)
    }

    private func processLocked(
        url: URL,
        folder: URL,
        context: (provider: AIProvider, model: String, credential: String, endpoint: URL?)
    ) async throws -> ScreenshotProcessingResult {
        let pinned = try SecureScreenshotFile.open(root: folder, candidate: url)
        let prepared = try await pinned.prepareForUploadAfterStabilityWindow()
        let analysis = try await analyzer.analyze(
            image: prepared.image,
            apiKey: context.credential,
            model: context.model,
            provider: context.provider,
            customEndpoint: context.endpoint
        )
        guard analysis.confidence >= 0.35 else {
            throw ScreenshotProcessingError.lowConfidence
        }
        let response = try await broker.renameScreenshot(
            at: url,
            snapshot: prepared.snapshot,
            analysis: analysis,
            provider: context.provider.rawValue,
            model: context.model
        )
        guard response.status != "skipped" else {
            throw ScreenshotProcessingError.skipped
        }
        guard let eventID = response.eventID,
              let renamedName = response.renamedName else {
            throw FileOperationBrokerError.invalidResponse
        }
        return ScreenshotProcessingResult(
            eventID: eventID,
            originalURL: url,
            renamedURL: url.deletingLastPathComponent().appendingPathComponent(renamedName)
        )
    }

    static func screenshotURLs(in folder: URL) -> [URL] {
        let keys: Set<URLResourceKey> = [
            .isRegularFileKey,
            .isSymbolicLinkKey,
            .creationDateKey,
            .contentModificationDateKey
        ]
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: folder,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        )) ?? []
        return urls
            .filter(ScreenshotDetector.looksLikeScreenshot)
            .filter {
                guard let values = try? $0.resourceValues(forKeys: keys) else { return false }
                return values.isRegularFile == true && values.isSymbolicLink != true
            }
            .sorted { lhs, rhs in
                let left = (try? lhs.resourceValues(forKeys: keys).creationDate) ?? .distantPast
                let right = (try? rhs.resourceValues(forKeys: keys).creationDate) ?? .distantPast
                return left > right
            }
    }

}

private final class ScreenshotProcessingLock {
    private let descriptor: Int32

    private init(descriptor: Int32) {
        self.descriptor = descriptor
    }

    static func acquire() throws -> ScreenshotProcessingLock {
        let root = stateRoot
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let path = root.appendingPathComponent("screenshot-processing.lock").path
        let descriptor = open(path, O_CREAT | O_RDWR | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw CocoaError(.fileWriteUnknown) }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            close(descriptor)
            if errno == EWOULDBLOCK { throw ScreenshotProcessingError.alreadyProcessing }
            throw CocoaError(.fileLocking)
        }
        return ScreenshotProcessingLock(descriptor: descriptor)
    }

    static var isLocked: Bool {
        let path = stateRoot.appendingPathComponent("screenshot-processing.lock").path
        guard FileManager.default.fileExists(atPath: path) else { return false }
        let descriptor = open(path, O_RDWR | O_CLOEXEC)
        guard descriptor >= 0 else { return false }
        defer { close(descriptor) }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            return errno == EWOULDBLOCK
        }
        flock(descriptor, LOCK_UN)
        return false
    }

    private static var stateRoot: URL {
        // Packaged code never accepts an environment-controlled lock path.
        // The override remains available only to source-level integration tests.
        guard Bundle.main.bundleURL.pathExtension.lowercased() != "app" else {
            return FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first!.appendingPathComponent("Froganize", isDirectory: true)
        }
        if let override = ProcessInfo.processInfo.environment["FROGANIZE_STATE_DIR"],
           override.hasPrefix("/") {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
        return FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first!.appendingPathComponent("Froganize", isDirectory: true)
    }

    func release() {
        flock(descriptor, LOCK_UN)
        close(descriptor)
    }
}
