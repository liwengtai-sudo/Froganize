#!/bin/zsh

set -eu
set -o pipefail

usage() {
  /usr/bin/printf \
    'Usage: %s [WORKSPACE]\n' \
    "${0:t}" >&2
}

set_plist_string() {
  local plist="$1"
  local key="$2"
  local value="$3"

  if ! /usr/libexec/PlistBuddy \
    -c "Set :${key} ${value}" \
    "${plist}" >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy \
      -c "Add :${key} string ${value}" \
      "${plist}"
  fi
}

if (( $# > 1 )); then
  usage
  exit 64
fi

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
APP_DIR="${HOME}/Applications"
APP_PATH="${APP_DIR}/DropNest.app"
ICON_PATH="${PROJECT_DIR}/assets/Froganize.icns"
ICON_RESOURCE_NAME="Froganize.icns"
DESKTOP_SHORTCUT="${HOME}/Desktop/Froganize.app"
LEGACY_DESKTOP_SHORTCUT="${HOME}/Desktop/DropNest.app"
DROP_NEST="${PROJECT_DIR}/.venv/bin/dropnest"
BUNDLE_IDENTIFIER="org.froganize.DropNest"
BUNDLE_VERSION="0.3.0"
BUNDLE_BUILD="2"
LEGACY_WORKSPACE="${HOME}/Documents/DropNestWorkspace"
DEFAULT_WORKSPACE="${HOME}/Documents/FroganizeWorkspace"

if (( $# == 1 )); then
  if [[ -z "$1" ]]; then
    /usr/bin/printf 'Workspace must not be empty.\n' >&2
    exit 64
  fi
  WORKSPACE_INPUT="$1"
elif [[ -e "${LEGACY_WORKSPACE}" || -L "${LEGACY_WORKSPACE}" ]]; then
  WORKSPACE_INPUT="${LEGACY_WORKSPACE}"
else
  WORKSPACE_INPUT="${DEFAULT_WORKSPACE}"
fi

if [[ "${WORKSPACE_INPUT}" == *$'\n'* || "${WORKSPACE_INPUT}" == *$'\r'* ]]; then
  /usr/bin/printf 'Workspace paths may not contain line breaks.\n' >&2
  exit 64
fi

if [[ ! -f "${ICON_PATH}" ]]; then
  /usr/bin/printf 'Froganize icon is missing:\n%s\n' "${ICON_PATH}" >&2
  exit 1
fi
if [[ ! -x "${DROP_NEST}" ]]; then
  /usr/bin/printf \
    'Project virtual environment is not ready:\n%s\n' \
    "${DROP_NEST}" >&2
  exit 1
fi

if (
  [[ -d "${WORKSPACE_INPUT}/Inbox" ]] &&
  [[ -d "${WORKSPACE_INPUT}/Timeline" ]] &&
  [[ -d "${WORKSPACE_INPUT}/.dropnest" ]] &&
  [[ -f "${WORKSPACE_INPUT}/.dropnest/config.json" ]] &&
  [[ -f "${WORKSPACE_INPUT}/.dropnest/history.jsonl" ]]
); then
  if ! "${DROP_NEST}" status "${WORKSPACE_INPUT}" >/dev/null; then
    /usr/bin/printf \
      'Warning: the existing workspace reported a status problem.\n' >&2
    /usr/bin/printf \
      'The launcher will be installed, but Froganize will keep blocking unsafe actions.\n' \
      >&2
  fi
else
  "${DROP_NEST}" init "${WORKSPACE_INPUT}"
fi

WORKSPACE="${WORKSPACE_INPUT:A}"
if [[ "${PROJECT_DIR}" == *$'\n'* || "${PROJECT_DIR}" == *$'\r'* ]]; then
  /usr/bin/printf 'Project paths may not contain line breaks.\n' >&2
  exit 1
fi

/bin/mkdir -p "${APP_DIR}"
/usr/bin/osacompile \
  -o "${APP_PATH}" \
  "${SCRIPT_DIR}/DropNestLauncher.applescript"
/bin/cp \
  "${ICON_PATH}" \
  "${APP_PATH}/Contents/Resources/${ICON_RESOURCE_NAME}"
APP_PLIST="${APP_PATH}/Contents/Info.plist"
set_plist_string "${APP_PLIST}" "CFBundleIdentifier" "${BUNDLE_IDENTIFIER}"
set_plist_string "${APP_PLIST}" "CFBundleDisplayName" "Froganize"
set_plist_string "${APP_PLIST}" "CFBundleName" "Froganize"
set_plist_string "${APP_PLIST}" "CFBundleIconFile" "${ICON_RESOURCE_NAME}"
set_plist_string \
  "${APP_PLIST}" \
  "CFBundleShortVersionString" \
  "${BUNDLE_VERSION}"
set_plist_string "${APP_PLIST}" "CFBundleVersion" "${BUNDLE_BUILD}"
set_plist_string \
  "${APP_PLIST}" \
  "LSApplicationCategoryType" \
  "public.app-category.utilities"
/bin/cp \
  "${SCRIPT_DIR}/launch_dropnest_web.sh" \
  "${APP_PATH}/Contents/Resources/launch_dropnest_web.sh"
/bin/chmod 755 "${APP_PATH}/Contents/Resources/launch_dropnest_web.sh"
/usr/bin/printf \
  '%s\n%s\n' \
  "${PROJECT_DIR}" \
  "${WORKSPACE}" \
  >"${APP_PATH}/Contents/Resources/launcher.conf"
/bin/chmod 600 "${APP_PATH}/Contents/Resources/launcher.conf"
/usr/bin/codesign --force --deep --sign - "${APP_PATH}"
/usr/bin/touch "${APP_PATH}"

/usr/bin/printf 'DropNest launcher installed at:\n%s\n' "${APP_PATH}"
/usr/bin/printf 'Bound project checkout:\n%s\n' "${PROJECT_DIR}"
/usr/bin/printf 'Bound workspace:\n%s\n' "${WORKSPACE}"
if [[ -e "${LEGACY_DESKTOP_SHORTCUT}" || -L "${LEGACY_DESKTOP_SHORTCUT}" ]]; then
  if (
    [[ -L "${LEGACY_DESKTOP_SHORTCUT}" ]] &&
    [[ "$(/usr/bin/readlink "${LEGACY_DESKTOP_SHORTCUT}")" == "${APP_PATH}" ]]
  ); then
    /bin/unlink "${LEGACY_DESKTOP_SHORTCUT}"
    /usr/bin/printf \
      'Legacy Desktop shortcut removed:\n%s\n' \
      "${LEGACY_DESKTOP_SHORTCUT}"
  else
    /usr/bin/printf \
      'Existing legacy Desktop item was not replaced:\n%s\n' \
      "${LEGACY_DESKTOP_SHORTCUT}"
  fi
fi
if [[ -e "${DESKTOP_SHORTCUT}" || -L "${DESKTOP_SHORTCUT}" ]]; then
  if (
    [[ -L "${DESKTOP_SHORTCUT}" ]] &&
    [[ "$(/usr/bin/readlink "${DESKTOP_SHORTCUT}")" == "${APP_PATH}" ]]
  ); then
    /usr/bin/printf 'Desktop shortcut preserved at:\n%s\n' "${DESKTOP_SHORTCUT}"
  else
    /usr/bin/printf \
      'Existing Desktop item was not replaced:\n%s\n' \
      "${DESKTOP_SHORTCUT}"
  fi
else
  /bin/mkdir -p "${HOME}/Desktop"
  /bin/ln -s "${APP_PATH}" "${DESKTOP_SHORTCUT}"
  /usr/bin/printf 'Desktop shortcut created at:\n%s\n' "${DESKTOP_SHORTCUT}"
fi
