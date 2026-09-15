#!/bin/zsh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
PYINSTALLER="${PROJECT_ROOT}/.venv/bin/pyinstaller"
SPEC_FILE="${PROJECT_ROOT}/packaging/Froganize.spec"
BUILD_ROOT="${PROJECT_ROOT}/build/macos"
DIST_ROOT="${PROJECT_ROOT}/dist/macos"
APP_PATH="${DIST_ROOT}/Froganize.app"
VERSION="0.3.0"
ARCH="$(/usr/bin/uname -m)"
DMG_TARGET="${FROGANIZE_DMG_TARGET:-applications}"
DEVELOPER_IDENTITY="${FROGANIZE_CODESIGN_IDENTITY:-}"
LOCAL_IDENTITY="${FROGANIZE_LOCAL_CODESIGN_IDENTITY:-}"
NOTARY_PROFILE="${FROGANIZE_NOTARY_PROFILE:-}"

if [[ -n "${DEVELOPER_IDENTITY}" && -n "${LOCAL_IDENTITY}" ]]; then
  /usr/bin/printf 'Error: set only one of FROGANIZE_CODESIGN_IDENTITY or FROGANIZE_LOCAL_CODESIGN_IDENTITY.\n' >&2
  exit 1
fi
if [[ -n "${NOTARY_PROFILE}" && -n "${LOCAL_IDENTITY}" ]]; then
  /usr/bin/printf 'Error: a local signing identity cannot be used for notarization.\n' >&2
  exit 1
fi
if [[ -n "${NOTARY_PROFILE}" && -z "${DEVELOPER_IDENTITY}" ]]; then
  /usr/bin/printf 'Error: notarization requires FROGANIZE_CODESIGN_IDENTITY.\n' >&2
  exit 1
fi
if [[ -n "${DEVELOPER_IDENTITY}" && "${DMG_TARGET}" != "applications" ]]; then
  /usr/bin/printf 'Error: Developer ID releases must use the Applications target.\n' >&2
  exit 1
fi

if [[ -n "${NOTARY_PROFILE}" ]]; then
  RELEASE_KIND="notarized"
elif [[ -n "${DEVELOPER_IDENTITY}" ]]; then
  RELEASE_KIND="signed-unnotarized"
elif [[ -n "${LOCAL_IDENTITY}" ]]; then
  RELEASE_KIND="local-signed"
else
  RELEASE_KIND="unsigned"
fi
DMG_NAME="Froganize-${VERSION}-macos-${ARCH}-${RELEASE_KIND}.dmg"
DMG_PATH="${DIST_ROOT}/${DMG_NAME}"
CHECKSUM_PATH="${DMG_PATH}.sha256"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  /usr/bin/printf 'Error: the macOS bundle must be built on macOS.\n' >&2
  exit 1
fi

if [[ ! -x "${PYINSTALLER}" ]]; then
  /usr/bin/printf 'Error: PyInstaller is missing. Run:\n' >&2
  /usr/bin/printf '  .venv/bin/python -m pip install -e '\''.[packaging]'\''\n' >&2
  exit 1
fi

if ! "${PROJECT_ROOT}/.venv/bin/python" -c 'import PySide6' 2>/dev/null; then
  /usr/bin/printf 'Error: the PySide6 GUI runtime is missing. Run:\n' >&2
  /usr/bin/printf '  .venv/bin/python -m pip install -e '\''.[packaging]'\''\n' >&2
  exit 1
fi

/bin/mkdir -p "${BUILD_ROOT}" "${DIST_ROOT}"
export PYINSTALLER_CONFIG_DIR="${BUILD_ROOT}/pyinstaller-config"
export FROGANIZE_CODESIGN_IDENTITY="${DEVELOPER_IDENTITY}"

"${PYINSTALLER}" \
  --noconfirm \
  --clean \
  --workpath "${BUILD_ROOT}" \
  --distpath "${DIST_ROOT}" \
  "${SPEC_FILE}"

if [[ ! -d "${APP_PATH}" ]]; then
  /usr/bin/printf 'Error: the expected application was not built: %s\n' "${APP_PATH}" >&2
  exit 1
fi

if [[ -n "${LOCAL_IDENTITY}" ]]; then
  # PyInstaller first emits its normal ad-hoc bundle. Re-signing the complete
  # bundle with one explicitly selected local identity gives future builds a
  # stable certificate-anchored designated requirement. A private/local
  # certificate has no trusted timestamp service and must never be notarized.
  /usr/bin/codesign \
    --force \
    --deep \
    --options runtime \
    --timestamp=none \
    --sign "${LOCAL_IDENTITY}" \
    "${APP_PATH}"
  LOCAL_REQUIREMENT="$(/usr/bin/codesign -d -r- "${APP_PATH}" 2>&1)"
  if [[ \
    "${LOCAL_REQUIREMENT}" != *'anchor = H"'* \
    || "${LOCAL_REQUIREMENT}" == *cdhash* \
    || "${LOCAL_REQUIREMENT}" != *'identifier "app.froganize.Froganize"'* \
  ]]; then
    /usr/bin/printf 'Error: local signature did not produce a certificate-anchored designated requirement.\n' >&2
    exit 1
  fi
fi

/usr/bin/codesign --verify --deep --strict --verbose=2 "${APP_PATH}"
"${PROJECT_ROOT}/.venv/bin/python" \
  "${PROJECT_ROOT}/scripts/smoke_macos_bundle.py" \
  "${APP_PATH}"

if [[ "${FROGANIZE_SKIP_DMG:-0}" == "1" ]]; then
  /usr/bin/printf '\nFroganize application bundle created.\n'
  /usr/bin/printf 'App: %s\n' "${APP_PATH}"
  /usr/bin/printf 'DMG generation was skipped by FROGANIZE_SKIP_DMG=1.\n'
  exit 0
fi

STAGING_DIR="$(/usr/bin/mktemp -d "${BUILD_ROOT}/dmg.XXXXXX")"
cleanup() {
  /bin/rm -rf -- "${STAGING_DIR}"
}
trap cleanup EXIT INT TERM

/usr/bin/ditto "${APP_PATH}" "${STAGING_DIR}/Froganize.app"
case "${DMG_TARGET}" in
  applications)
    /bin/ln -s /Applications "${STAGING_DIR}/Applications"
    TARGET_LABEL="Applications"
    ;;
  desktop)
    if [[ ! -d "${HOME}/Desktop" ]]; then
      /usr/bin/printf 'Error: Desktop does not exist: %s\n' "${HOME}/Desktop" >&2
      exit 1
    fi
    /bin/ln -s "${HOME}/Desktop" "${STAGING_DIR}/Desktop"
    TARGET_LABEL="Desktop (local-machine candidate)"
    ;;
  *)
    /usr/bin/printf 'Error: FROGANIZE_DMG_TARGET must be applications or desktop.\n' >&2
    exit 1
    ;;
esac
/bin/rm -f -- "${DMG_PATH}" "${CHECKSUM_PATH}"
/usr/bin/hdiutil create \
  -volname "Froganize" \
  -srcfolder "${STAGING_DIR}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

if [[ -n "${DEVELOPER_IDENTITY}" ]]; then
  /usr/bin/codesign \
    --force \
    --sign "${DEVELOPER_IDENTITY}" \
    --timestamp \
    "${DMG_PATH}"
  /usr/bin/codesign --verify --strict --verbose=2 "${DMG_PATH}"
elif [[ -n "${LOCAL_IDENTITY}" ]]; then
  /usr/bin/codesign \
    --force \
    --sign "${LOCAL_IDENTITY}" \
    --timestamp=none \
    "${DMG_PATH}"
  /usr/bin/codesign --verify --strict --verbose=2 "${DMG_PATH}"
fi

if [[ -n "${NOTARY_PROFILE}" ]]; then
  /usr/bin/xcrun notarytool submit "${DMG_PATH}" \
    --keychain-profile "${NOTARY_PROFILE}" \
    --wait
  /usr/bin/xcrun stapler staple "${DMG_PATH}"
  /usr/bin/xcrun stapler validate "${DMG_PATH}"
  /usr/sbin/spctl \
    --assess \
    --type open \
    --context context:primary-signature \
    --verbose=2 \
    "${DMG_PATH}"
fi

/usr/bin/shasum -a 256 "${DMG_PATH}" >"${CHECKSUM_PATH}"

/usr/bin/printf '\nFroganize local distribution candidate created.\n'
/usr/bin/printf 'App: %s\n' "${APP_PATH}"
/usr/bin/printf 'DMG: %s\n' "${DMG_PATH}"
/usr/bin/printf 'SHA-256: %s\n' "${CHECKSUM_PATH}"
/usr/bin/printf 'Install target shown in DMG: %s\n' "${TARGET_LABEL}"
if [[ "${RELEASE_KIND}" == "notarized" ]]; then
  /usr/bin/printf 'Release state: Developer ID signed, notarized, stapled, and assessed.\n'
elif [[ "${RELEASE_KIND}" == "signed-unnotarized" ]]; then
  /usr/bin/printf 'Important: Developer ID signed but not notarized. Do not publish it yet.\n'
elif [[ "${RELEASE_KIND}" == "local-signed" ]]; then
  /usr/bin/printf 'Local state: signed with a stable private identity, not Developer ID, and not notarized. Do not publish it.\n'
else
  /usr/bin/printf 'Important: this build is ad-hoc signed and not notarized. Do not publish it yet.\n'
fi
