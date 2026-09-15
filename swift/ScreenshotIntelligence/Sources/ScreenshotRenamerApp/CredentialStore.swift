import Darwin
import Foundation
import Security
import ScreenshotRenamerCore

enum CredentialStoreError: LocalizedError {
    case keychain(OSStatus)

    var errorDescription: String? {
        switch self {
        case let .keychain(status):
            return SecCopyErrorMessageString(status, nil) as String? ?? "钥匙串操作失败（\(status)）"
        }
    }
}

final class CredentialStore {
    enum Source: String {
        case keychain = "macOS 钥匙串"
        case environment = "运行环境"
        case envFile = "项目 .env.local"
    }

    /// Checks whether a credential exists without asking Keychain to return
    /// (and therefore decrypt) the secret value. This method is safe for UI
    /// refreshes, state polling, and enablement preflight checks.
    func hasAPIKey(for provider: AIProvider) -> Bool {
        credentialSource(for: provider) != nil
    }

    /// Returns only non-secret provenance metadata. Packaged applications use
    /// Keychain exclusively. Development environment variables are detected by
    /// name so `swift run` keeps its explicit convenience path.
    func credentialSource(for provider: AIProvider) -> Source? {
        if keychainContainsCredential(for: provider) {
            return .keychain
        }

        guard Bundle.main.bundleURL.pathExtension.lowercased() != "app" else {
            return nil
        }
        // `getenv` is used only as a presence probe; the value is not decoded
        // or copied until an explicit test/process action calls loadAPIKey.
        if getenv(provider.environmentVariable) != nil {
            return .environment
        }
        return nil
    }

    /// Loads secret material. Callers must restrict this to an explicit
    /// provider request boundary (`testConnection` or screenshot processing).
    func loadAPIKey(for provider: AIProvider) -> (key: String, source: Source)? {
        if let key = loadFromKeychain(for: provider), isUsable(key) {
            return (key, .keychain)
        }

        // Packaged builds use Keychain only. Environment and .env.local loading
        // are explicit conveniences for `swift run`, never a bundle search path.
        guard Bundle.main.bundleURL.pathExtension.lowercased() != "app" else {
            return nil
        }

        if let key = ProcessInfo.processInfo.environment[provider.environmentVariable], isUsable(key) {
            return (key, .environment)
        }

        if ProcessInfo.processInfo.environment["FROGANIZE_ALLOW_ENV_FILE"] == "1" {
            for fileURL in candidateEnvironmentFiles() {
                if let key = loadFromEnvironmentFile(fileURL, variable: provider.environmentVariable), isUsable(key) {
                    return (key, .envFile)
                }
            }
        }

        return nil
    }

    func saveToKeychain(_ key: String, for provider: AIProvider) throws {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard isUsable(trimmed) else {
            throw CocoaError(.validationMissingMandatoryProperty)
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: provider.environmentVariable
        ]
        let valueData = Data(trimmed.utf8)
        let updateStatus = SecItemUpdate(
            query as CFDictionary,
            [kSecValueData as String: valueData] as CFDictionary
        )
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw CredentialStoreError.keychain(updateStatus)
        }

        var addQuery = query
        addQuery[kSecValueData as String] = valueData
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw CredentialStoreError.keychain(addStatus)
        }
    }

    func removeFromKeychain(for provider: AIProvider) throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: provider.environmentVariable
        ]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw CredentialStoreError.keychain(status)
        }
    }

    private func loadFromKeychain(for provider: AIProvider) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: provider.environmentVariable,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    private func keychainContainsCredential(for provider: AIProvider) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: provider.environmentVariable,
            // Returning attributes is deliberately metadata-only. Do not add
            // kSecReturnData here: doing so can prompt for secret access during
            // ordinary panel refreshes.
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var item: CFTypeRef?
        return SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess
    }

    private func candidateEnvironmentFiles() -> [URL] {
        var starts: [URL] = [URL(fileURLWithPath: FileManager.default.currentDirectoryPath)]
        starts.append(Bundle.main.bundleURL.deletingLastPathComponent())
        if let executableURL = Bundle.main.executableURL {
            starts.append(executableURL.deletingLastPathComponent())
        }

        var results: [URL] = []
        var seen = Set<String>()
        for start in starts {
            var directory = start.standardizedFileURL
            for _ in 0..<9 {
                let candidate = directory.appendingPathComponent(".env.local")
                if seen.insert(candidate.path).inserted,
                   FileManager.default.fileExists(atPath: candidate.path) {
                    results.append(candidate)
                }
                let parent = directory.deletingLastPathComponent()
                if parent.path == directory.path { break }
                directory = parent
            }
        }
        return results
    }

    private func loadFromEnvironmentFile(_ url: URL, variable: String) -> String? {
        guard let contents = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        for line in contents.components(separatedBy: .newlines) {
            var value = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if value.hasPrefix("export ") {
                value.removeFirst("export ".count)
            }
            let prefix = "\(variable)="
            guard value.hasPrefix(prefix) else { continue }
            value.removeFirst(prefix.count)
            value = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if value.count >= 2,
               (value.hasPrefix("\"") && value.hasSuffix("\"") || value.hasPrefix("'") && value.hasSuffix("'")) {
                value.removeFirst()
                value.removeLast()
            }
            return value
        }
        return nil
    }

    private func isUsable(_ key: String) -> Bool {
        key.trimmingCharacters(in: .whitespacesAndNewlines).count > 20
    }

    private func service(for provider: AIProvider) -> String {
        switch provider {
        case .openAI:
            return "app.froganize.Froganize.ScreenshotIntelligence.credentials.openai"
        case .openRouter:
            return "app.froganize.Froganize.ScreenshotIntelligence.credentials.openrouter"
        case .alibabaBailian:
            return "app.froganize.Froganize.ScreenshotIntelligence.credentials.alibaba-bailian"
        case .customOpenAICompatible:
            return "app.froganize.Froganize.ScreenshotIntelligence.credentials.custom-compatible"
        }
    }
}
