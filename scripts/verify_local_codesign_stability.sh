#!/bin/zsh

set -euo pipefail

usage() {
  /usr/bin/printf '%s\n' \
    'Compare the nested Screenshot Intelligence identity in two Froganize builds.' \
    '' \
    'Usage:' \
    '  ./scripts/verify_local_codesign_stability.sh OLD_FROGANIZE_APP NEW_FROGANIZE_APP'
}

fail() {
  /usr/bin/printf 'Error: %s\n' "$1" >&2
  exit 1
}

if (( $# == 1 )) && [[ "$1" == "--help" || "$1" == "-h" ]]; then
  usage
  exit 0
fi
if (( $# != 2 )); then
  usage >&2
  exit 2
fi
if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  fail 'code-signing stability can only be verified on macOS.'
fi

EXPECTED_BUNDLE_ID="app.froganize.Froganize.ScreenshotIntelligence"
AGENT_RELATIVE="Contents/Library/LoginItems/FroganizeScreenshotAgent.app"

inspect_agent() {
  local app_path="$1"
  local label="$2"
  local agent_path="${app_path}/${AGENT_RELATIVE}"
  local plist_path="${agent_path}/Contents/Info.plist"
  local bundle_id
  local signature_info
  local raw_requirement
  local requirement
  local cdhash

  if [[ ! -d "${app_path}" || -L "${app_path}" ]]; then
    fail "${label} app must be a non-symlinked application bundle: ${app_path}"
  fi
  if [[ ! -d "${agent_path}" || -L "${agent_path}" || ! -f "${plist_path}" ]]; then
    fail "${label} app is missing the fixed nested Screenshot Intelligence bundle."
  fi
  /usr/bin/codesign --verify --deep --strict --verbose=2 "${agent_path}"
  bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${plist_path}" 2>/dev/null || true)"
  if [[ "${bundle_id}" != "${EXPECTED_BUNDLE_ID}" ]]; then
    fail "${label} nested bundle identifier is unexpected: ${bundle_id}"
  fi
  signature_info="$(/usr/bin/codesign -dvvv "${agent_path}" 2>&1)"
  if [[ "${signature_info}" == *'Signature=adhoc'* ]]; then
    fail "${label} nested agent is still ad-hoc signed."
  fi
  raw_requirement="$(/usr/bin/codesign -d -r- "${agent_path}" 2>&1)"
  if [[ "${raw_requirement}" != *'designated => '* ]]; then
    fail "${label} nested agent has no readable designated requirement."
  fi
  requirement="designated => ${raw_requirement#*designated => }"
  if [[ \
    "${requirement}" != *'anchor = H"'* \
    || "${requirement}" == *cdhash* \
    || "${requirement}" != *"identifier \"${EXPECTED_BUNDLE_ID}\""* \
  ]]; then
    fail "${label} nested designated requirement is not stable and certificate-anchored."
  fi
  cdhash="$(/usr/bin/printf '%s\n' "${signature_info}" | /usr/bin/sed -n 's/^CDHash=//p' | /usr/bin/head -n 1)"

  typeset -g "${label}_REQUIREMENT=${requirement}"
  typeset -g "${label}_CDHASH=${cdhash}"
}

inspect_agent "$1" OLD
inspect_agent "$2" NEW

if [[ "${OLD_REQUIREMENT}" != "${NEW_REQUIREMENT}" ]]; then
  /usr/bin/printf '%s\n' \
    'Old requirement:' "${OLD_REQUIREMENT}" \
    'New requirement:' "${NEW_REQUIREMENT}" >&2
  fail 'the nested designated requirement changed between builds.'
fi

/usr/bin/printf '%s\n' \
  'Stable local identity verified for the nested Screenshot Intelligence agent.' \
  "Bundle ID: ${EXPECTED_BUNDLE_ID}" \
  "Old CDHash: ${OLD_CDHASH:-unavailable}" \
  "New CDHash: ${NEW_CDHASH:-unavailable}" \
  "Designated requirement: ${NEW_REQUIREMENT}"
