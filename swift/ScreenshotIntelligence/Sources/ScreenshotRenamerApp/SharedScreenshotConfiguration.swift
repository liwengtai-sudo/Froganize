import Foundation
import ScreenshotRenamerCore

enum SharedScreenshotConfiguration {
    static let changedNotification = Notification.Name(
        "app.froganize.screenshot-intelligence.configuration-changed.v1"
    )

    static let enabledKey = "isEnabled"
    static let uploadConsentKey = "screenshotIntelligenceUploadConsent.v1"
    static let providerKey = "aiProvider"
    static let folderPathKey = "folderPath"
    static let lastRenameEventIDKey = "lastRenameEventID"
    static let statusMessageKey = "externalStatusMessage"
    static let customEndpointKey = "customProviderEndpoint"
    static let customModelKey = "customProviderModel"

    static func modelKey(for provider: AIProvider) -> String {
        "modelName.\(provider.rawValue)"
    }

    static func provider(in defaults: UserDefaults = .standard) -> AIProvider {
        // The public product has one provider-neutral configuration surface.
        // Legacy preset values remain untouched in UserDefaults, but are no
        // longer selected or exposed to the UI.
        .customOpenAICompatible
    }

    static func model(
        for provider: AIProvider,
        in defaults: UserDefaults = .standard
    ) -> String {
        if provider == .customOpenAICompatible {
            let saved = defaults.string(forKey: customModelKey) ?? ""
            return provider.supports(model: saved) ? saved : provider.defaultModel
        }
        let saved = defaults.string(forKey: modelKey(for: provider))
        return provider.supports(model: saved ?? "") ? saved! : provider.defaultModel
    }

    static func customEndpoint(in defaults: UserDefaults = .standard) -> URL? {
        guard let value = defaults.string(forKey: customEndpointKey) else { return nil }
        return CustomProviderEndpoint.validated(value)
    }

    static func customEndpointString(in defaults: UserDefaults = .standard) -> String {
        customEndpoint(in: defaults)?.absoluteString ?? ""
    }

    static func customModel(in defaults: UserDefaults = .standard) -> String {
        let value = defaults.string(forKey: customModelKey) ?? ""
        return AIProvider.customOpenAICompatible.supports(model: value) ? value : ""
    }

    static func folder(in defaults: UserDefaults = .standard) -> URL {
        if let path = defaults.string(forKey: folderPathKey), path.hasPrefix("/") {
            return URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
        }
        return FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first!
    }

    static func enabled(in defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: uploadConsentKey)
            && (defaults.object(forKey: enabledKey) as? Bool ?? false)
    }

    static func uploadConsent(in defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: uploadConsentKey)
    }

    static func lastRenameEventID(in defaults: UserDefaults = .standard) -> UUID? {
        defaults.string(forKey: lastRenameEventIDKey).flatMap(UUID.init(uuidString:))
    }

    static func publishChange() {
        UserDefaults.standard.synchronize()
        DistributedNotificationCenter.default().postNotificationName(
            changedNotification,
            object: nil,
            userInfo: nil,
            deliverImmediately: true
        )
    }
}
