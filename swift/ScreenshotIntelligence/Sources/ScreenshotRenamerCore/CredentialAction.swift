import Foundation

/// Keeps credential persistence and provider validation as two explicit user
/// actions. In particular, `save` has no analyzer parameter and therefore
/// cannot initiate a provider request.
public enum CredentialAction {
    public static func save(
        _ apiKey: String,
        persist: (String) throws -> Void
    ) rethrows {
        try persist(apiKey)
    }

    public static func testConnection(
        apiKey: String,
        model: String,
        provider: AIProvider,
        customEndpoint: URL? = nil,
        analyzer: ScreenshotAnalyzing
    ) async throws {
        try await analyzer.validate(
            apiKey: apiKey,
            model: model,
            provider: provider,
            customEndpoint: customEndpoint
        )
    }
}
