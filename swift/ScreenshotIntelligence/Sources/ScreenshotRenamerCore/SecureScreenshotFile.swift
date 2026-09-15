import Darwin
import Foundation

public enum SecureScreenshotFileError: LocalizedError, Equatable, Sendable {
    case rootMustBeAbsolute
    case unsafeRoot
    case candidateNotDirectChild
    case unsafeCandidateName
    case symbolicLink
    case notRegularFile
    case emptyFile
    case fileTooLarge
    case fileChanged
    case unreadable

    public var errorDescription: String? {
        switch self {
        case .rootMustBeAbsolute: return "截图目录必须是绝对路径"
        case .unsafeRoot: return "截图目录包含无法安全打开的路径组件"
        case .candidateNotDirectChild: return "只能处理截图目录的顶层文件"
        case .unsafeCandidateName: return "截图文件名不安全"
        case .symbolicLink: return "符号链接不会被上传"
        case .notRegularFile: return "只能上传普通截图文件"
        case .emptyFile: return "截图文件为空"
        case .fileTooLarge: return "截图文件超过 40 MiB 安全限制"
        case .fileChanged: return "截图在上传前发生变化，已安全停止"
        case .unreadable: return "无法安全读取截图文件"
        }
    }

    /// Only failures that commonly mean macOS is still writing a newly
    /// created screenshot are eligible for the watcher's bounded retry.
    /// Permission, path and file-type failures stay terminal.
    public var isTransientDuringWrite: Bool {
        switch self {
        case .emptyFile, .fileChanged:
            return true
        case .rootMustBeAbsolute, .unsafeRoot, .candidateNotDirectChild,
             .unsafeCandidateName, .symbolicLink, .notRegularFile,
             .fileTooLarge, .unreadable:
            return false
        }
    }
}

public struct SecurePreparedScreenshot: Sendable {
    public let image: PreparedImage
    public let snapshot: FileSnapshot

    public init(image: PreparedImage, snapshot: FileSnapshot) {
        self.image = image
        self.snapshot = snapshot
    }
}

/// Pins the configured root and leaf with descriptor-relative, no-follow opens.
/// The root descriptor stays open until preparation finishes, so neither a
/// symlink swap nor path replacement can redirect the bytes sent to a provider.
public final class SecureScreenshotFile: @unchecked Sendable {
    public static let maximumSourceBytes: Int64 = 40 * 1_024 * 1_024
    public static let defaultStabilityDelayNanoseconds: UInt64 = 350_000_000

    private let rootDescriptor: Int32
    private let fileDescriptor: Int32
    private let basename: String
    private let initialIdentity: FileIdentity

    private init(
        rootDescriptor: Int32,
        fileDescriptor: Int32,
        basename: String,
        identity: FileIdentity
    ) {
        self.rootDescriptor = rootDescriptor
        self.fileDescriptor = fileDescriptor
        self.basename = basename
        self.initialIdentity = identity
    }

    deinit {
        close(fileDescriptor)
        close(rootDescriptor)
    }

    public static func open(root: URL, candidate: URL) throws -> SecureScreenshotFile {
        // Do not call `standardizedFileURL` here: Foundation may canonicalize
        // `/private/tmp` to the `/tmp` symlink. Descriptor walking below is the
        // sole authority and deliberately refuses every symlink component.
        guard root.path.hasPrefix("/") else {
            throw SecureScreenshotFileError.rootMustBeAbsolute
        }
        guard !root.pathComponents.contains(".."),
              !root.pathComponents.contains("."),
              !candidate.pathComponents.contains(".."),
              !candidate.pathComponents.contains(".") else {
            throw SecureScreenshotFileError.unsafeRoot
        }
        guard candidate.deletingLastPathComponent().path == root.path else {
            throw SecureScreenshotFileError.candidateNotDirectChild
        }
        let basename = candidate.lastPathComponent
        guard FileOperationContract.isSafeBasename(basename) else {
            throw SecureScreenshotFileError.unsafeCandidateName
        }

        let rootFD = try openDirectoryWithoutFollowingSymlinks(root)
        do {
            let fileFD = openat(rootFD, basename, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
            guard fileFD >= 0 else {
                if errno == ELOOP { throw SecureScreenshotFileError.symbolicLink }
                throw SecureScreenshotFileError.unreadable
            }
            do {
                let identity = try FileIdentity.capture(descriptor: fileFD)
                try validate(identity)
                return SecureScreenshotFile(
                    rootDescriptor: rootFD,
                    fileDescriptor: fileFD,
                    basename: basename,
                    identity: identity
                )
            } catch {
                close(fileFD)
                throw error
            }
        } catch {
            close(rootFD)
            throw error
        }
    }

    public func prepareForUpload() throws -> SecurePreparedScreenshot {
        try verifyPinnedIdentity()
        let length = Int(initialIdentity.size)
        var bytes = Data(count: length)
        let didReadAll = bytes.withUnsafeMutableBytes { buffer -> Bool in
            guard let base = buffer.baseAddress else { return length == 0 }
            var offset = 0
            while offset < length {
                let count = pread(fileDescriptor, base.advanced(by: offset), length - offset, off_t(offset))
                if count < 0 {
                    if errno == EINTR { continue }
                    return false
                }
                if count == 0 { return false }
                offset += count
            }
            return true
        }
        guard didReadAll else { throw SecureScreenshotFileError.unreadable }
        try verifyPinnedIdentity()

        let image = try ImagePreprocessor.prepare(bytes)
        // Image decoding can take measurable time. Check once more immediately
        // before the caller is allowed to invoke an AI provider.
        try verifyPinnedIdentity()
        return SecurePreparedScreenshot(
            image: image,
            snapshot: initialIdentity.fileSnapshot
        )
    }

    /// Wait through a short stability window while both descriptors stay
    /// pinned, then repeat the identity checks immediately before upload.
    public func prepareForUploadAfterStabilityWindow(
        nanoseconds: UInt64 = SecureScreenshotFile.defaultStabilityDelayNanoseconds
    ) async throws -> SecurePreparedScreenshot {
        if nanoseconds > 0 {
            try await Task.sleep(nanoseconds: nanoseconds)
        }
        return try prepareForUpload()
    }

    private func verifyPinnedIdentity() throws {
        let currentFD = try FileIdentity.capture(descriptor: fileDescriptor)
        guard currentFD == initialIdentity else {
            throw SecureScreenshotFileError.fileChanged
        }

        var pathStat = stat()
        let result = fstatat(rootDescriptor, basename, &pathStat, AT_SYMLINK_NOFOLLOW)
        guard result == 0 else { throw SecureScreenshotFileError.fileChanged }
        let pathIdentity = FileIdentity(pathStat)
        guard pathIdentity == initialIdentity,
              pathStat.st_mode & S_IFMT == S_IFREG else {
            throw SecureScreenshotFileError.fileChanged
        }
    }

    private static func validate(_ identity: FileIdentity) throws {
        guard identity.mode & UInt32(S_IFMT) == UInt32(S_IFREG) else {
            throw SecureScreenshotFileError.notRegularFile
        }
        guard identity.size > 0 else { throw SecureScreenshotFileError.emptyFile }
        guard identity.size <= maximumSourceBytes else {
            throw SecureScreenshotFileError.fileTooLarge
        }
    }

    private static func openDirectoryWithoutFollowingSymlinks(_ root: URL) throws -> Int32 {
        var current = Darwin.open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard current >= 0 else { throw SecureScreenshotFileError.unsafeRoot }

        let components = root.pathComponents.dropFirst()
        for component in components {
            guard !component.isEmpty, component != ".", component != "..", !component.contains("/") else {
                close(current)
                throw SecureScreenshotFileError.unsafeRoot
            }
            let next = openat(current, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard next >= 0 else {
                close(current)
                if errno == ELOOP { throw SecureScreenshotFileError.symbolicLink }
                throw SecureScreenshotFileError.unsafeRoot
            }
            close(current)
            current = next
        }
        return current
    }
}

private struct FileIdentity: Equatable {
    let device: UInt64
    let inode: UInt64
    let mode: UInt32
    let size: Int64
    let modificationSeconds: Int64
    let modificationNanoseconds: Int64
    let changeSeconds: Int64
    let changeNanoseconds: Int64

    init(_ value: stat) {
        device = UInt64(value.st_dev)
        inode = UInt64(value.st_ino)
        mode = UInt32(value.st_mode)
        size = Int64(value.st_size)
        modificationSeconds = Int64(value.st_mtimespec.tv_sec)
        modificationNanoseconds = Int64(value.st_mtimespec.tv_nsec)
        changeSeconds = Int64(value.st_ctimespec.tv_sec)
        changeNanoseconds = Int64(value.st_ctimespec.tv_nsec)
    }

    static func capture(descriptor: Int32) throws -> FileIdentity {
        var value = stat()
        guard fstat(descriptor, &value) == 0 else {
            throw SecureScreenshotFileError.unreadable
        }
        return FileIdentity(value)
    }

    var fileSnapshot: FileSnapshot {
        let (seconds, overflow) = modificationSeconds.multipliedReportingOverflow(by: 1_000_000_000)
        let (mtime, additionOverflow) = seconds.addingReportingOverflow(modificationNanoseconds)
        return FileSnapshot(
            device: device,
            inode: inode,
            mode: mode,
            size: size,
            modificationTimeNanoseconds: overflow || additionOverflow ? Int64.min : mtime
        )
    }
}
