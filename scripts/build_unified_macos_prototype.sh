#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
AGENT_PROJECT="${FROGANIZE_AGENT_PROJECT:-${PROJECT_ROOT}/swift/ScreenshotIntelligence}"
OUTER_BUILD_SCRIPT="${PROJECT_ROOT}/scripts/build_macos_distribution.sh"
AGENT_BUILD_SCRIPT="${AGENT_PROJECT}/Scripts/build-app.sh"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
PYINSTALLER="${PROJECT_ROOT}/.venv/bin/pyinstaller"
HELPER_ENTRY="${PROJECT_ROOT}/scripts/froganize_fileops_entry.py"
HELPER_MODULE="${PROJECT_ROOT}/src/dropnest/agent_cli.py"
BUILD_ROOT="${PROJECT_ROOT}/build/unified"
HELPER_DIST="${BUILD_ROOT}/helper-dist"
SOURCE_APP="${PROJECT_ROOT}/dist/macos/Froganize.app"
OUTPUT_ROOT="${PROJECT_ROOT}/dist/unified"
OUTPUT_APP="${OUTPUT_ROOT}/Froganize.app"
HELPER_DESTINATION="${OUTPUT_APP}/Contents/MacOS/FroganizeFileOps"
NESTED_AGENT="${OUTPUT_APP}/Contents/Library/LoginItems/FroganizeScreenshotAgent.app"
UNIFIED_VERSION="${FROGANIZE_UNIFIED_VERSION:-0.3.0}"

fail() {
  /usr/bin/printf 'Error: %s\n' "$1" >&2
  exit 1
}

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  fail "the unified application bundle must be built on macOS."
fi
if [[ -n "${FROGANIZE_NOTARY_PROFILE:-}" ]]; then
  fail "this local prototype does not create or notarize a release artifact."
fi
if [[ -n "${FROGANIZE_CODESIGN_IDENTITY:-}" && -n "${FROGANIZE_LOCAL_CODESIGN_IDENTITY:-}" ]]; then
  fail "set only one of FROGANIZE_CODESIGN_IDENTITY or FROGANIZE_LOCAL_CODESIGN_IDENTITY."
fi
if [[ ! -d "${AGENT_PROJECT}" ]]; then
  fail "the Screenshot Intelligence project is missing: ${AGENT_PROJECT}"
fi
AGENT_PROJECT="$(CDPATH= cd -- "${AGENT_PROJECT}" && pwd)"
AGENT_BUILD_SCRIPT="${AGENT_PROJECT}/Scripts/build-app.sh"
if [[ ! -x "${AGENT_BUILD_SCRIPT}" ]]; then
  fail "the Screenshot Intelligence build script is missing or not executable."
fi
if [[ ! -x "${OUTER_BUILD_SCRIPT}" ]]; then
  fail "the Froganize macOS build script is missing or not executable."
fi
if [[ ! -x "${PYTHON}" || ! -x "${PYINSTALLER}" ]]; then
  fail "the local packaging environment is incomplete; install .[packaging]."
fi
if [[ ! -f "${HELPER_ENTRY}" || ! -f "${HELPER_MODULE}" ]]; then
  fail "the deterministic Froganize file-operation helper source is missing."
fi
if [[ ! "${UNIFIED_VERSION}" =~ '^[0-9]+\.[0-9]+\.[0-9]+$' ]]; then
  fail "FROGANIZE_UNIFIED_VERSION must use the form major.minor.patch."
fi

/bin/mkdir -p "${BUILD_ROOT}" "${OUTPUT_ROOT}"

FROGANIZE_SKIP_DMG=1 "${OUTER_BUILD_SCRIPT}"
if [[ ! -d "${SOURCE_APP}" ]]; then
  fail "the outer Froganize bundle was not produced."
fi

/bin/rm -rf -- \
  "${BUILD_ROOT}/helper-build" \
  "${BUILD_ROOT}/helper-spec" \
  "${HELPER_DIST}"
/bin/mkdir -p \
  "${BUILD_ROOT}/helper-build" \
  "${BUILD_ROOT}/helper-spec" \
  "${HELPER_DIST}"
export PYINSTALLER_CONFIG_DIR="${BUILD_ROOT}/pyinstaller-config"
"${PYINSTALLER}" \
  --noconfirm \
  --clean \
  --onefile \
  --console \
  --name FroganizeFileOps \
  --paths "${PROJECT_ROOT}/src" \
  --workpath "${BUILD_ROOT}/helper-build" \
  --specpath "${BUILD_ROOT}/helper-spec" \
  --distpath "${HELPER_DIST}" \
  "${HELPER_ENTRY}"
if [[ ! -x "${HELPER_DIST}/FroganizeFileOps" ]]; then
  fail "PyInstaller did not produce the file-operation helper."
fi

AGENT_BUILD_MARKER="${BUILD_ROOT}/agent-build-started"
/usr/bin/touch "${AGENT_BUILD_MARKER}"
(
  cd -- "${AGENT_PROJECT}"
  "${AGENT_BUILD_SCRIPT}"
)

agent_candidates=(
  "${AGENT_PROJECT}/build/Froganize Screenshot Intelligence.app"
  "${AGENT_PROJECT}/build/FroganizeScreenshotAgent.app"
  "${AGENT_PROJECT}/build/AI 截图命名.app"
)
fresh_agents=()
for candidate in "${agent_candidates[@]}"; do
  if [[ ! -d "${candidate}" || -L "${candidate}" ]]; then
    continue
  fi
  candidate_executable="$(
    /usr/libexec/PlistBuddy \
      -c 'Print :CFBundleExecutable' \
      "${candidate}/Contents/Info.plist" 2>/dev/null || true
  )"
  if [[ \
    -z "${candidate_executable}" \
    || "${candidate_executable}" == */* \
    || "${candidate_executable}" == "." \
    || "${candidate_executable}" == ".." \
  ]]; then
    continue
  fi
  candidate_binary="${candidate}/Contents/MacOS/${candidate_executable}"
  if [[ -x "${candidate_binary}" && "${candidate_binary}" -nt "${AGENT_BUILD_MARKER}" ]]; then
    fresh_agents+=("${candidate}")
  fi
done
if (( ${#fresh_agents[@]} != 1 )); then
  fail "the agent build must produce exactly one fresh supported application bundle."
fi
AGENT_APP="${fresh_agents[1]}"

/bin/rm -rf -- "${OUTPUT_APP}"
/usr/bin/ditto "${SOURCE_APP}" "${OUTPUT_APP}"
/bin/mkdir -p "${OUTPUT_APP}/Contents/Library/LoginItems"
/bin/cp "${HELPER_DIST}/FroganizeFileOps" "${HELPER_DESTINATION}"
/bin/chmod 755 "${HELPER_DESTINATION}"
/usr/bin/ditto "${AGENT_APP}" "${NESTED_AGENT}"

/usr/libexec/PlistBuddy \
  -c "Set :CFBundleShortVersionString ${UNIFIED_VERSION}" \
  "${OUTPUT_APP}/Contents/Info.plist"
/usr/libexec/PlistBuddy \
  -c "Set :CFBundleShortVersionString ${UNIFIED_VERSION}" \
  "${NESTED_AGENT}/Contents/Info.plist"

DEVELOPER_IDENTITY="${FROGANIZE_CODESIGN_IDENTITY:-}"
LOCAL_IDENTITY="${FROGANIZE_LOCAL_CODESIGN_IDENTITY:-}"
if [[ -n "${DEVELOPER_IDENTITY}" ]]; then
  SIGN_IDENTITY="${DEVELOPER_IDENTITY}"
  SIGN_MODE="developer-id"
elif [[ -n "${LOCAL_IDENTITY}" ]]; then
  SIGN_IDENTITY="${LOCAL_IDENTITY}"
  SIGN_MODE="local"
else
  SIGN_IDENTITY="-"
  SIGN_MODE="adhoc"
fi
sign_executable() {
  if [[ "${SIGN_MODE}" == "adhoc" ]]; then
    /usr/bin/codesign --force --sign - "$1"
  elif [[ "${SIGN_MODE}" == "local" ]]; then
    /usr/bin/codesign --force --options runtime --timestamp=none --sign "${SIGN_IDENTITY}" "$1"
  else
    /usr/bin/codesign --force --options runtime --timestamp --sign "${SIGN_IDENTITY}" "$1"
  fi
}
sign_bundle() {
  if [[ "${SIGN_MODE}" == "adhoc" ]]; then
    /usr/bin/codesign --force --deep --sign - "$1"
  elif [[ "${SIGN_MODE}" == "local" ]]; then
    /usr/bin/codesign --force --deep --options runtime --timestamp=none --sign "${SIGN_IDENTITY}" "$1"
  else
    /usr/bin/codesign --force --deep --options runtime --timestamp --sign "${SIGN_IDENTITY}" "$1"
  fi
}

verify_local_requirement() {
  local expected_identifier="$2"
  local requirement
  requirement="$(/usr/bin/codesign -d -r- "$1" 2>&1)"
  if [[ \
    "${requirement}" != *'anchor = H"'* \
    || "${requirement}" == *cdhash* \
    || "${requirement}" != *"identifier \"${expected_identifier}\""* \
  ]]; then
    fail "local signature for $1 is not anchored to a stable certificate."
  fi
}

verify_agent_identifier() {
  local agent_identifier
  agent_identifier="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$1/Contents/Info.plist" 2>/dev/null || true)"
  if [[ "${agent_identifier}" != "app.froganize.Froganize.ScreenshotIntelligence" ]]; then
    fail "the nested agent bundle identifier is unexpected: ${agent_identifier}"
  fi
}

# Sign from the deepest nested code outward after every payload is in place.
sign_executable "${HELPER_DESTINATION}"
sign_bundle "${NESTED_AGENT}"
sign_bundle "${OUTPUT_APP}"

/usr/bin/codesign --verify --deep --strict --verbose=2 "${NESTED_AGENT}"
/usr/bin/codesign --verify --deep --strict --verbose=2 "${OUTPUT_APP}"
if [[ "${SIGN_MODE}" == "local" ]]; then
  verify_agent_identifier "${NESTED_AGENT}"
  verify_local_requirement \
    "${NESTED_AGENT}" \
    "app.froganize.Froganize.ScreenshotIntelligence"
  verify_local_requirement \
    "${OUTPUT_APP}" \
    "app.froganize.Froganize"
fi
"${PYTHON}" "${PROJECT_ROOT}/scripts/smoke_unified_macos_bundle.py" "${OUTPUT_APP}"

/usr/bin/printf '\nFroganize %s unified local prototype created.\n' "${UNIFIED_VERSION}"
/usr/bin/printf 'App: %s\n' "${OUTPUT_APP}"
/usr/bin/printf 'Helper: Contents/MacOS/FroganizeFileOps\n'
/usr/bin/printf 'Agent: Contents/Library/LoginItems/FroganizeScreenshotAgent.app\n'
if [[ "${SIGN_MODE}" == "adhoc" ]]; then
  /usr/bin/printf 'Signature: ad-hoc (local testing only; not notarized).\n'
elif [[ "${SIGN_MODE}" == "local" ]]; then
  /usr/bin/printf 'Signature: %s (stable private local identity; not Developer ID; not notarized).\n' "${SIGN_IDENTITY}"
else
  /usr/bin/printf 'Signature: %s (local prototype; not notarized).\n' "${SIGN_IDENTITY}"
fi
