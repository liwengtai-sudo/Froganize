#!/bin/zsh

set -eu
set -o pipefail

usage() {
  /usr/bin/printf \
    'Usage: %s WORKSPACE [PROJECT_ROOT]\n' \
    "${0:t}" >&2
}

if (( $# < 1 || $# > 2 )); then
  usage
  exit 64
fi

SCRIPT_DIR="${0:A:h}"
WORKSPACE="$1"
PROJECT_ROOT="${2:-${SCRIPT_DIR:h}}"

if [[ -z "${WORKSPACE}" || "${WORKSPACE}" != /* ]]; then
  /usr/bin/printf 'Workspace must be a non-empty absolute path.\n' >&2
  exit 64
fi
if [[ -z "${PROJECT_ROOT}" || "${PROJECT_ROOT}" != /* ]]; then
  /usr/bin/printf 'Project root must be a non-empty absolute path.\n' >&2
  exit 64
fi
if (
  [[ "${WORKSPACE}" == *$'\n'* || "${WORKSPACE}" == *$'\r'* ]] ||
  [[ "${PROJECT_ROOT}" == *$'\n'* || "${PROJECT_ROOT}" == *$'\r'* ]]
); then
  /usr/bin/printf 'Launcher paths may not contain line breaks.\n' >&2
  exit 64
fi

DROP_NEST="${PROJECT_ROOT}/.venv/bin/dropnest"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
PORT="8765"
URL="http://127.0.0.1:${PORT}/"
HEALTH_URL="${URL}api/health"
STATUS_URL="${URL}api/status"
LOG_PATH="/tmp/dropnest-web-${UID}.log"
PID_PATH="/tmp/dropnest-web-${UID}.pid"

listener_pid() {
  local output
  output=$(
    /usr/sbin/lsof -nP -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true
  )
  [[ -n "${output}" ]] || return 0
  /usr/bin/printf '%s\n' "${output%%$'\n'*}"
}

server_ready() {
  /usr/bin/curl \
    --noproxy "*" \
    --fail \
    --silent \
    --show-error \
    --max-time 1 \
    "${HEALTH_URL}" |
    /usr/bin/grep -q '"mode": "desktop"'
}

server_matches_workspace() {
  local response
  response=$(
    /usr/bin/curl \
      --noproxy "*" \
      --fail \
      --silent \
      --show-error \
      --max-time 1 \
      "${STATUS_URL}" 2>/dev/null
  ) || return 1

  FROGANIZE_STATUS="${response}" \
    FROGANIZE_WORKSPACE="${WORKSPACE}" \
    "${PYTHON}" -c '
import json
import os
from pathlib import Path

payload = json.loads(os.environ["FROGANIZE_STATUS"])
actual = payload.get("status", {}).get("workspace")
expected = os.environ["FROGANIZE_WORKSPACE"]
if not isinstance(actual, str):
    raise SystemExit(1)
raise SystemExit(
    0
    if Path(actual).resolve(strict=False) == Path(expected).resolve(strict=False)
    else 1
)
'
}

server_matches_binding() {
  local pid="$1"
  local command
  [[ "${pid}" == <-> ]] || return 1
  command=$(/bin/ps -p "${pid}" -o command= 2>/dev/null || true)
  (
    [[ "${command}" == *"${PROJECT_ROOT}"* ]] &&
    [[ "${command}" == *"dropnest web"* ]] &&
    [[ "${command}" == *"${WORKSPACE}"* ]]
  )
}

stop_bound_server() {
  local pid="$1"
  /bin/kill -0 "${pid}" 2>/dev/null || return 0
  if ! server_matches_binding "${pid}"; then
    /usr/bin/printf 'The service owner changed before restart; aborting.\n' >&2
    exit 1
  fi
  /bin/kill -TERM "${pid}"
  for _attempt in {1..30}; do
    /bin/kill -0 "${pid}" 2>/dev/null || return 0
    /bin/sleep 0.1
  done
  /usr/bin/printf 'Could not stop the previous DropNest service.\n' >&2
  exit 1
}

if [[ ! -x "${DROP_NEST}" ]]; then
  /usr/bin/printf 'Froganize executable not found: %s\n' "${DROP_NEST}" >&2
  exit 1
fi
if [[ ! -x "${PYTHON}" ]]; then
  /usr/bin/printf 'Froganize Python runtime not found: %s\n' "${PYTHON}" >&2
  exit 1
fi

if (
  [[ ! -d "${WORKSPACE}/Inbox" ]] ||
  [[ ! -d "${WORKSPACE}/Timeline" ]] ||
  [[ ! -d "${WORKSPACE}/.dropnest" ]] ||
  [[ ! -f "${WORKSPACE}/.dropnest/config.json" ]] ||
  [[ ! -f "${WORKSPACE}/.dropnest/history.jsonl" ]]
); then
  /usr/bin/printf 'Froganize workspace is not ready: %s\n' "${WORKSPACE}" >&2
  exit 1
fi

LISTENER_PID="$(listener_pid)"
if [[ -n "${LISTENER_PID}" ]]; then
  if server_ready; then
    if server_matches_workspace; then
      /usr/bin/open "${URL}"
      exit 0
    fi
    /usr/bin/printf \
      'Port %s is used by Froganize with a different workspace.\n' \
      "${PORT}" >&2
    exit 1
  fi

  if ! server_matches_binding "${LISTENER_PID}"; then
    /usr/bin/printf \
      'Port %s is already used by another application.\n' \
      "${PORT}" >&2
    exit 1
  fi

  stop_bound_server "${LISTENER_PID}"
fi

/usr/bin/nohup \
  "${DROP_NEST}" web "${WORKSPACE}" --port "${PORT}" --no-browser \
  >"${LOG_PATH}" 2>&1 </dev/null &
SERVER_PID=$!
/usr/bin/printf '%s\n' "${SERVER_PID}" >"${PID_PATH}"

for _attempt in {1..50}; do
  if server_ready; then
    /usr/bin/open "${URL}"
    exit 0
  fi
  /bin/sleep 0.1
done

/usr/bin/printf \
  'Froganize dashboard did not start. Check log: %s\n' \
  "${LOG_PATH}" >&2
exit 1
