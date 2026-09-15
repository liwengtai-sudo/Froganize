#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
APP_DIR="$PROJECT_DIR/build/Froganize Screenshot Intelligence.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/.build/cache/clang"
export CLANG_MODULE_CACHE_PATH="$PROJECT_DIR/.build/cache/clang"
export SWIFTPM_MODULECACHE_OVERRIDE="$PROJECT_DIR/.build/cache/clang"

swift build -c release --disable-sandbox
BIN_DIR="$(swift build -c release --show-bin-path --disable-sandbox)"

mkdir -p "$MACOS_DIR"
cp "$BIN_DIR/ScreenshotRenamer" "$MACOS_DIR/ScreenshotRenamer"
cp "$PROJECT_DIR/Packaging/Info.plist" "$CONTENTS_DIR/Info.plist"
chmod 755 "$MACOS_DIR/ScreenshotRenamer"

DEVELOPER_IDENTITY="${FROGANIZE_CODESIGN_IDENTITY:-}"
LOCAL_IDENTITY="${FROGANIZE_LOCAL_CODESIGN_IDENTITY:-}"
if [[ -n "$DEVELOPER_IDENTITY" && -n "$LOCAL_IDENTITY" ]]; then
    print -u2 "Error: set only one of FROGANIZE_CODESIGN_IDENTITY or FROGANIZE_LOCAL_CODESIGN_IDENTITY."
    exit 1
fi

if [[ -n "$DEVELOPER_IDENTITY" ]]; then
    codesign --force --deep --options runtime --timestamp --sign "$DEVELOPER_IDENTITY" "$APP_DIR"
elif [[ -n "$LOCAL_IDENTITY" ]]; then
    codesign --force --deep --options runtime --timestamp=none --sign "$LOCAL_IDENTITY" "$APP_DIR"
    LOCAL_REQUIREMENT="$(codesign -d -r- "$APP_DIR" 2>&1)"
    if [[ \
        "$LOCAL_REQUIREMENT" != *'anchor = H"'* \
        || "$LOCAL_REQUIREMENT" == *cdhash* \
        || "$LOCAL_REQUIREMENT" != *'identifier "app.froganize.Froganize.ScreenshotIntelligence"'* \
    ]]; then
        print -u2 "Error: local signature did not produce a certificate-anchored designated requirement."
        exit 1
    fi
else
    codesign --force --deep --sign - "$APP_DIR"
fi
codesign --verify --deep --strict --verbose=2 "$APP_DIR"
print "$APP_DIR"
