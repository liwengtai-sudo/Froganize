#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/.build/cache/clang"
export CLANG_MODULE_CACHE_PATH="$PROJECT_DIR/.build/cache/clang"
export SWIFTPM_MODULECACHE_OVERRIDE="$PROJECT_DIR/.build/cache/clang"
swift run --disable-sandbox ScreenshotRenamer
