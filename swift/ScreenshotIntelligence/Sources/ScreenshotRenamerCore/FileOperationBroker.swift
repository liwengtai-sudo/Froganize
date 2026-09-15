import Darwin
import Foundation

public enum FileOperationAction: String, Codable, Sendable {
    case configureScreenshotRoot = "configure_screenshot_root"
    case renameScreenshot = "rename_screenshot"
    case undoScreenshotRename = "undo_screenshot_rename"
}

public struct FileSnapshot: Codable, Equatable, Sendable {
    public let device: UInt64
    public let inode: UInt64
    public let mode: UInt32
    public let size: Int64
    public let modificationTimeNanoseconds: Int64

    public init(
        device: UInt64,
        inode: UInt64,
        mode: UInt32,
        size: Int64,
        modificationTimeNanoseconds: Int64
    ) {
        self.device = device
        self.inode = inode
        self.mode = mode
        self.size = size
        self.modificationTimeNanoseconds = modificationTimeNanoseconds
    }

    public static func capture(_ url: URL) throws -> FileSnapshot {
        var value = stat()
        let result: Int32 = url.withUnsafeFileSystemRepresentation { path in
            guard let path else { return Int32(-1) }
            return lstat(path, &value)
        }

        guard result == 0 else {
            throw FileOperationBrokerError.sourceUnavailable
        }
        guard value.st_mode & S_IFMT == S_IFREG else {
            throw FileOperationBrokerError.sourceIsNotRegularFile
        }

        let seconds = Int64(value.st_mtimespec.tv_sec)
        let nanoseconds = Int64(value.st_mtimespec.tv_nsec)
        let (scaledSeconds, overflowed) = seconds.multipliedReportingOverflow(by: 1_000_000_000)
        guard !overflowed else {
            throw FileOperationBrokerError.invalidSnapshot
        }
        let (modificationTime, additionOverflowed) = scaledSeconds.addingReportingOverflow(nanoseconds)
        guard !additionOverflowed else {
            throw FileOperationBrokerError.invalidSnapshot
        }

        return FileSnapshot(
            device: UInt64(value.st_dev),
            inode: UInt64(value.st_ino),
            mode: UInt32(value.st_mode),
            size: Int64(value.st_size),
            modificationTimeNanoseconds: modificationTime
        )
    }

    private enum CodingKeys: String, CodingKey {
        case device
        case inode
        case mode
        case size
        case modificationTimeNanoseconds = "mtime_ns"
    }
}

public struct FileOperationRequest: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let action: FileOperationAction
    public let sourceRoot: String?
    public let sourceName: String?
    public let snapshot: FileSnapshot?
    public let analysis: ScreenshotAnalysis?
    public let provider: String?
    public let model: String?
    public let eventID: UUID?

    public static func configureScreenshotRoot(
        _ root: URL,
        requestID: UUID = UUID()
    ) -> FileOperationRequest {
        FileOperationRequest(
            requestID: requestID,
            action: .configureScreenshotRoot,
            sourceRoot: root.standardizedFileURL.path
        )
    }

    public static func renameScreenshot(
        sourceName: String,
        snapshot: FileSnapshot,
        analysis: ScreenshotAnalysis,
        provider: String,
        model: String,
        requestID: UUID = UUID()
    ) throws -> FileOperationRequest {
        guard FileOperationContract.isSafeBasename(sourceName) else {
            throw FileOperationBrokerError.invalidSourceName
        }
        return FileOperationRequest(
            requestID: requestID,
            action: .renameScreenshot,
            sourceName: sourceName,
            snapshot: snapshot,
            analysis: analysis,
            provider: provider,
            model: model
        )
    }

    public static func undoScreenshotRename(
        eventID: UUID? = nil,
        requestID: UUID = UUID()
    ) -> FileOperationRequest {
        FileOperationRequest(
            requestID: requestID,
            action: .undoScreenshotRename,
            eventID: eventID
        )
    }

    private init(
        requestID: UUID,
        action: FileOperationAction,
        sourceRoot: String? = nil,
        sourceName: String? = nil,
        snapshot: FileSnapshot? = nil,
        analysis: ScreenshotAnalysis? = nil,
        provider: String? = nil,
        model: String? = nil,
        eventID: UUID? = nil
    ) {
        self.schemaVersion = FileOperationContract.schemaVersion
        self.requestID = requestID
        self.action = action
        self.sourceRoot = sourceRoot
        self.sourceName = sourceName
        self.snapshot = snapshot
        self.analysis = analysis
        self.provider = provider
        self.model = model
        self.eventID = eventID
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case action
        case sourceRoot = "source_root"
        case sourceName = "source_name"
        case snapshot
        case analysis
        case provider
        case model
        case eventID = "event_id"
    }
}

public struct FileOperationErrorPayload: Codable, Equatable, Sendable {
    public let code: String
    public let message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }
}

public struct FileOperationResponse: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID?
    public let status: String
    public let eventID: UUID?
    public let originalName: String?
    public let renamedName: String?
    public let screenshotRoot: String?
    public let restoredName: String?
    public let undoOfEventID: UUID?
    public let reasonCode: String?
    public let reason: String?
    public let error: FileOperationErrorPayload?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case status
        case eventID = "event_id"
        case originalName = "original_name"
        case renamedName = "renamed_name"
        case screenshotRoot = "screenshot_root"
        case restoredName = "restored_name"
        case undoOfEventID = "undo_of_event_id"
        case reasonCode = "reason_code"
        case reason
        case error
    }
}

public enum FileOperationContract {
    public static let schemaVersion = 1
    public static let maximumRequestBytes = 64 * 1024
    public static let maximumResponseBytes = 64 * 1024

    public static func encode(_ request: FileOperationRequest) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(request)
    }

    public static func decodeResponse(
        _ data: Data,
        expecting request: FileOperationRequest
    ) throws -> FileOperationResponse {
        guard !data.isEmpty, data.count <= maximumResponseBytes else {
            throw FileOperationBrokerError.invalidResponse
        }

        let response: FileOperationResponse
        do {
            response = try JSONDecoder().decode(FileOperationResponse.self, from: data)
        } catch {
            throw FileOperationBrokerError.invalidResponse
        }

        guard response.schemaVersion == schemaVersion else {
            throw FileOperationBrokerError.unsupportedSchemaVersion(response.schemaVersion)
        }

        if response.status == "error" {
            if let responseID = response.requestID,
               responseID != request.requestID {
                throw FileOperationBrokerError.mismatchedRequestID
            }
            let error = response.error ?? FileOperationErrorPayload(
                code: "unknown_error",
                message: "文件操作助手拒绝了请求"
            )
            throw FileOperationBrokerError.helperRejected(code: error.code, message: error.message)
        }
        guard response.requestID == request.requestID else {
            throw FileOperationBrokerError.mismatchedRequestID
        }

        let expectedStatus: String
        switch request.action {
        case .configureScreenshotRoot:
            expectedStatus = "configured"
        case .renameScreenshot:
            expectedStatus = "renamed"
        case .undoScreenshotRename:
            expectedStatus = "undone"
        }
        guard response.status == expectedStatus || response.status == "skipped" else {
            throw FileOperationBrokerError.unexpectedStatus(response.status)
        }

        if response.status == "skipped" {
            guard request.action != .configureScreenshotRoot,
                  response.reasonCode?.isEmpty == false,
                  response.reason?.isEmpty == false else {
                throw FileOperationBrokerError.invalidResponse
            }
            return response
        }

        if let originalName = response.originalName,
           !isSafeBasename(originalName) {
            throw FileOperationBrokerError.invalidResponse
        }
        if let renamedName = response.renamedName,
           !isSafeBasename(renamedName) {
            throw FileOperationBrokerError.invalidResponse
        }
        if let restoredName = response.restoredName,
           !isSafeBasename(restoredName) {
            throw FileOperationBrokerError.invalidResponse
        }
        if request.action == .renameScreenshot,
           (response.eventID == nil || response.originalName == nil || response.renamedName == nil) {
            throw FileOperationBrokerError.invalidResponse
        }
        if request.action == .undoScreenshotRename,
           (response.restoredName == nil || response.renamedName == nil) {
            throw FileOperationBrokerError.invalidResponse
        }

        return response
    }

    public static func isSafeBasename(_ value: String) -> Bool {
        !value.isEmpty
            && value != "."
            && value != ".."
            && !value.contains("/")
            && !value.contains("\\")
            && !value.contains("\0")
    }
}

public enum FileOperationBrokerError: LocalizedError, Equatable {
    case helperPathMustBeAbsolute
    case helperUnavailable
    case helperNotExecutable
    case launchFailed(String)
    case timedOut
    case helperExited(code: Int32, diagnostic: String?)
    case requestTooLarge
    case responseTooLarge
    case invalidResponse
    case unsupportedSchemaVersion(Int)
    case mismatchedRequestID
    case unexpectedStatus(String)
    case helperRejected(code: String, message: String)
    case invalidSourceName
    case sourceUnavailable
    case sourceIsNotRegularFile
    case invalidSnapshot

    public var errorDescription: String? {
        switch self {
        case .helperPathMustBeAbsolute:
            return "文件操作助手路径必须是绝对路径"
        case .helperUnavailable:
            return "找不到 Froganize 文件操作助手；文件未被修改"
        case .helperNotExecutable:
            return "Froganize 文件操作助手不可执行；文件未被修改"
        case let .launchFailed(message):
            return "无法启动 Froganize 文件操作助手：\(message)"
        case .timedOut:
            return "Froganize 文件操作助手响应超时；请检查文件是否保持原状"
        case let .helperExited(code, diagnostic):
            let suffix = diagnostic.map { "：\($0)" } ?? ""
            return "Froganize 文件操作助手异常退出（\(code)）\(suffix)"
        case .requestTooLarge:
            return "截图智能请求超过安全大小限制；文件未被修改"
        case .responseTooLarge:
            return "Froganize 文件操作助手返回了过大的响应"
        case .invalidResponse:
            return "Froganize 文件操作助手返回了无法验证的响应"
        case let .unsupportedSchemaVersion(version):
            return "Froganize 文件操作协议版本不兼容（\(version)）"
        case .mismatchedRequestID:
            return "Froganize 文件操作助手返回了不匹配的请求编号"
        case let .unexpectedStatus(status):
            return "Froganize 文件操作助手返回了意外状态：\(status)"
        case let .helperRejected(_, message):
            return message
        case .invalidSourceName:
            return "截图文件名不安全；文件未被修改"
        case .sourceUnavailable:
            return "截图在处理前已不存在或无法读取"
        case .sourceIsNotRegularFile:
            return "只能处理普通截图文件，符号链接不会上传或改名"
        case .invalidSnapshot:
            return "无法生成可靠的截图状态快照"
        }
    }
}

public final class FileOperationBrokerClient: @unchecked Sendable {
    public static let helperEnvironmentVariable = "FROGANIZE_FILEOPS_HELPER"

    private let explicitExecutableURL: URL?
    private let environment: [String: String]
    private let bundleURL: URL
    private let timeout: TimeInterval
    private let fileManager: FileManager
    private let processEnvironment: [String: String]?

    public init(
        executableURL: URL? = nil,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        bundleURL: URL = Bundle.main.bundleURL,
        timeout: TimeInterval = 15,
        fileManager: FileManager = .default,
        processEnvironment: [String: String]? = nil
    ) {
        self.explicitExecutableURL = executableURL
        self.environment = environment
        self.bundleURL = bundleURL
        self.timeout = timeout
        self.fileManager = fileManager
        self.processEnvironment = processEnvironment
    }

    public func configureScreenshotRoot(_ root: URL) async throws -> FileOperationResponse {
        try await execute(.configureScreenshotRoot(root))
    }

    public func renameScreenshot(
        at sourceURL: URL,
        snapshot: FileSnapshot,
        analysis: ScreenshotAnalysis,
        provider: String,
        model: String
    ) async throws -> FileOperationResponse {
        let request = try FileOperationRequest.renameScreenshot(
            sourceName: sourceURL.lastPathComponent,
            snapshot: snapshot,
            analysis: analysis,
            provider: provider,
            model: model
        )
        return try await execute(request)
    }

    public func undoScreenshotRename(eventID: UUID? = nil) async throws -> FileOperationResponse {
        try await execute(.undoScreenshotRename(eventID: eventID))
    }

    public func resolvedExecutableURL() throws -> URL {
        let candidate: URL
        if let explicitExecutableURL {
            candidate = explicitExecutableURL
        } else if let override = environment[Self.helperEnvironmentVariable], !override.isEmpty {
            guard override.hasPrefix("/") else {
                throw FileOperationBrokerError.helperPathMustBeAbsolute
            }
            candidate = URL(fileURLWithPath: override)
        } else {
            guard let outerContents = Self.outerApplicationContents(for: bundleURL) else {
                throw FileOperationBrokerError.helperUnavailable
            }
            candidate = outerContents
                .appendingPathComponent("MacOS", isDirectory: true)
                .appendingPathComponent("FroganizeFileOps", isDirectory: false)
        }

        guard fileManager.fileExists(atPath: candidate.path) else {
            throw FileOperationBrokerError.helperUnavailable
        }
        guard fileManager.isExecutableFile(atPath: candidate.path) else {
            throw FileOperationBrokerError.helperNotExecutable
        }
        return candidate
    }

    private static func outerApplicationContents(for nestedBundleURL: URL) -> URL? {
        var current = nestedBundleURL.standardizedFileURL.deletingLastPathComponent()
        while current.path != "/" {
            if current.lastPathComponent == "Contents",
               current.deletingLastPathComponent().pathExtension.lowercased() == "app" {
                return current
            }
            let parent = current.deletingLastPathComponent()
            guard parent.path != current.path else { return nil }
            current = parent
        }
        return nil
    }

    public func execute(_ request: FileOperationRequest) async throws -> FileOperationResponse {
        try await Task.detached(priority: .utility) { [self] in
            try executeSynchronously(request)
        }.value
    }

    private func executeSynchronously(_ request: FileOperationRequest) throws -> FileOperationResponse {
        let executableURL = try resolvedExecutableURL()
        var requestData = try FileOperationContract.encode(request)
        requestData.append(0x0A)
        guard requestData.count <= FileOperationContract.maximumRequestBytes else {
            throw FileOperationBrokerError.requestTooLarge
        }

        let process = Process()
        let standardInput = Pipe()
        let standardOutput = Pipe()
        let standardError = Pipe()
        let completion = DispatchSemaphore(value: 0)

        process.executableURL = executableURL
        process.arguments = []
        process.standardInput = standardInput
        process.standardOutput = standardOutput
        process.standardError = standardError
        if let processEnvironment {
            process.environment = processEnvironment
        }
        process.terminationHandler = { _ in completion.signal() }

        do {
            try process.run()
        } catch {
            throw FileOperationBrokerError.launchFailed(error.localizedDescription)
        }

        // Drain both pipes while the helper runs. Waiting for termination first
        // can deadlock when either pipe fills. Captures are bounded; an
        // oversized helper response is terminated instead of growing memory.
        let outputCapture = BoundedPipeCapture(
            handle: standardOutput.fileHandleForReading,
            limit: FileOperationContract.maximumResponseBytes
        ) {
            if process.isRunning { process.terminate() }
        }
        let errorCapture = BoundedPipeCapture(
            handle: standardError.fileHandleForReading,
            limit: 8 * 1_024
        ) {
            // stderr is diagnostic only. Keep draining and truncate it rather
            // than terminating an otherwise valid helper operation.
        }
        outputCapture.start()
        errorCapture.start()

        do {
            try standardInput.fileHandleForWriting.write(contentsOf: requestData)
            try standardInput.fileHandleForWriting.close()
        } catch {
            if process.isRunning { process.terminate() }
            throw FileOperationBrokerError.launchFailed(error.localizedDescription)
        }

        guard completion.wait(timeout: .now() + timeout) == .success else {
            if process.isRunning { process.terminate() }
            _ = completion.wait(timeout: .now() + 2)
            throw FileOperationBrokerError.timedOut
        }

        outputCapture.wait()
        errorCapture.wait()
        let output = outputCapture.data
        let diagnostic = Self.sanitizeDiagnostic(errorCapture.data)

        guard !outputCapture.exceededLimit else {
            throw FileOperationBrokerError.responseTooLarge
        }

        do {
            let response = try FileOperationContract.decodeResponse(output, expecting: request)
            guard process.terminationStatus == 0 else {
                throw FileOperationBrokerError.helperExited(
                    code: process.terminationStatus,
                    diagnostic: diagnostic
                )
            }
            return response
        } catch let error as FileOperationBrokerError {
            if process.terminationStatus != 0,
               error == .invalidResponse {
                throw FileOperationBrokerError.helperExited(
                    code: process.terminationStatus,
                    diagnostic: diagnostic
                )
            }
            throw error
        }
    }

    private static func sanitizeDiagnostic(_ data: Data) -> String? {
        guard !data.isEmpty else { return nil }
        let decoded = String(decoding: data.prefix(600), as: UTF8.self)
        let cleaned = decoded.unicodeScalars.map { scalar -> Character in
            CharacterSet.controlCharacters.contains(scalar) ? " " : Character(String(scalar))
        }
        let value = String(cleaned)
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
        return value.isEmpty ? nil : value
    }
}

private final class BoundedPipeCapture: @unchecked Sendable {
    private let handle: FileHandle
    private let limit: Int
    private let onLimitExceeded: @Sendable () -> Void
    private let group = DispatchGroup()
    private let lock = NSLock()
    private var storage = Data()
    private var didExceedLimit = false

    init(
        handle: FileHandle,
        limit: Int,
        onLimitExceeded: @escaping @Sendable () -> Void
    ) {
        self.handle = handle
        self.limit = limit
        self.onLimitExceeded = onLimitExceeded
    }

    func start() {
        group.enter()
        DispatchQueue.global(qos: .utility).async { [self] in
            defer { group.leave() }
            while true {
                guard let chunk = try? handle.read(upToCount: 8 * 1_024),
                      !chunk.isEmpty else { return }
                lock.lock()
                let remaining = max(0, limit + 1 - storage.count)
                if remaining > 0 { storage.append(chunk.prefix(remaining)) }
                let exceeded = storage.count > limit
                if exceeded { didExceedLimit = true }
                lock.unlock()
                if exceeded {
                    onLimitExceeded()
                    // Continue draining to EOF to prevent the child from
                    // blocking even after the bounded capture is full.
                }
            }
        }
    }

    func wait() {
        group.wait()
    }

    var data: Data {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    var exceededLimit: Bool {
        lock.lock()
        defer { lock.unlock() }
        return didExceedLimit
    }
}
