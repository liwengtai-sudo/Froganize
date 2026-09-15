#!/bin/sh

set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
STORE="$PROJECT_DIR/Sources/ScreenshotRenamerApp/CredentialStore.swift"
CONTROL="$PROJECT_DIR/Sources/ScreenshotRenamerApp/ScreenshotControlCLI.swift"
MODEL="$PROJECT_DIR/Sources/ScreenshotRenamerApp/AppModel.swift"
PROCESSOR="$PROJECT_DIR/Sources/ScreenshotRenamerApp/ScreenshotProcessingService.swift"

fail() {
    echo "Keychain policy check failed: $1" >&2
    exit 1
}

grep -q 'func hasAPIKey(for provider: AIProvider)' "$STORE" \
    || fail "missing metadata-only hasAPIKey"
grep -q 'kSecReturnAttributes as String: true' "$STORE" \
    || fail "metadata query does not request attributes"
grep -q 'app\.froganize\.Froganize\.ScreenshotIntelligence\.credentials\.' "$STORE" \
    || fail "Froganize credential service namespace is missing"

if grep -q 'com\.screenshotrenamer\.' "$STORE"; then
    fail "legacy ScreenshotRenamer credential services are still queried"
fi

# Raw key material may be loaded only at explicit provider request boundaries:
# test_connection and screenshot processing. Status, refresh, provider changes,
# and enablement checks must stay metadata-only.
[ "$(grep -c 'credentials\.loadAPIKey' "$CONTROL" || true)" -eq 1 ] \
    || fail "control path should load a secret only in test_connection"
[ "$(grep -c 'credentials\.loadAPIKey' "$MODEL" || true)" -eq 1 ] \
    || fail "menu app should load a secret only in testConnection"
[ "$(grep -c 'credentials\.loadAPIKey' "$PROCESSOR" || true)" -eq 1 ] \
    || fail "processing service should load one secret at upload boundary"

echo "Keychain access policy check passed."
