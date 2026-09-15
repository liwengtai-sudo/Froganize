#!/bin/zsh

set -euo pipefail

IDENTITY_NAME="${FROGANIZE_LOCAL_IDENTITY_NAME:-Froganize Local Code Signing}"
KEYCHAIN_PATH="${FROGANIZE_LOCAL_KEYCHAIN:-${HOME}/Library/Keychains/login.keychain-db}"
VALID_DAYS="3650"
ASSUME_YES=0

usage() {
  /usr/bin/printf '%s\n' \
    'Create one private, self-signed macOS code-signing identity for local Froganize builds.' \
    '' \
    'Usage:' \
    '  ./scripts/create_local_codesign_identity.sh [--name NAME] [--keychain PATH] [--yes]' \
    '' \
    'This command changes the selected macOS keychain and user trust settings.' \
    'It never runs as part of a normal build and never uses sudo.' \
    'The generated private key is non-exportable and its ACL is limited to /usr/bin/codesign.' \
    'The identity is for this Mac only; it is not Developer ID and must not be published.'
}

fail() {
  /usr/bin/printf 'Error: %s\n' "$1" >&2
  exit 1
}

while (( $# > 0 )); do
  case "$1" in
    --name)
      (( $# >= 2 )) || fail '--name requires a value.'
      IDENTITY_NAME="$2"
      shift 2
      ;;
    --keychain)
      (( $# >= 2 )) || fail '--keychain requires a value.'
      KEYCHAIN_PATH="$2"
      shift 2
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  fail 'a local macOS signing identity can only be created on macOS.'
fi
if [[ ! "${IDENTITY_NAME}" =~ '^[A-Za-z0-9][A-Za-z0-9 ._-]{2,63}$' ]]; then
  fail 'the identity name must be 3-64 ASCII letters, digits, spaces, dots, underscores, or hyphens.'
fi
if [[ "${KEYCHAIN_PATH}" != /* || ! -f "${KEYCHAIN_PATH}" || -L "${KEYCHAIN_PATH}" ]]; then
  fail 'the keychain must be an existing, non-symlinked absolute file path.'
fi
if [[ ! -x /usr/bin/openssl || ! -x /usr/bin/security || ! -x /usr/bin/codesign ]]; then
  fail 'required macOS signing tools are unavailable.'
fi
if /usr/bin/security find-certificate -c "${IDENTITY_NAME}" "${KEYCHAIN_PATH}" >/dev/null 2>&1; then
  fail "a certificate named '${IDENTITY_NAME}' already exists; do not create an ambiguous duplicate."
fi

/usr/bin/printf '%s\n' \
  '' \
  'This one-time setup will:' \
  "  - create '${IDENTITY_NAME}' in ${KEYCHAIN_PATH};" \
  '  - trust that certificate for code signing for this macOS user;' \
  '  - install a non-exportable private key usable by /usr/bin/codesign;' \
  '  - keep all generated temporary key material private and remove it on exit.' \
  '' \
  'It does not create an Apple Developer identity and does not make builds safe to publish.' \
  'Software running as this user could invoke codesign and try to use this local key, so' \
  'create it only on a Mac you control.' \
  ''

if (( ASSUME_YES == 0 )); then
  read -r "CONFIRMATION?Type CREATE to modify this keychain: "
  if [[ "${CONFIRMATION}" != "CREATE" ]]; then
    /usr/bin/printf 'No changes made.\n'
    exit 2
  fi
fi

umask 077
TEMP_ROOT="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/froganize-local-codesign.XXXXXX")"
CERTIFICATE_IMPORTED=0
CREATED_FINGERPRINT=""
cleanup() {
  local exit_status=$?
  if (( exit_status != 0 )) && (( CERTIFICATE_IMPORTED == 1 )) && [[ -n "${CREATED_FINGERPRINT}" ]]; then
    /usr/bin/printf 'Creation failed; removing only the identity created by this run (%s).\n' "${CREATED_FINGERPRINT}" >&2
    /usr/bin/security delete-identity \
      -Z "${CREATED_FINGERPRINT}" \
      -t \
      "${KEYCHAIN_PATH}" >/dev/null 2>&1 || \
    /usr/bin/security delete-certificate \
      -Z "${CREATED_FINGERPRINT}" \
      "${KEYCHAIN_PATH}" >/dev/null 2>&1 || \
      /usr/bin/printf 'Warning: automatic rollback failed. In Keychain Access, remove only certificate SHA-1 %s before retrying.\n' "${CREATED_FINGERPRINT}" >&2
  fi
  /bin/rm -rf -- "${TEMP_ROOT}"
  return "${exit_status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

OPENSSL_CONFIG="${TEMP_ROOT}/certificate.cnf"
PRIVATE_KEY="${TEMP_ROOT}/private-key.pem"
CERTIFICATE="${TEMP_ROOT}/certificate.pem"

{
  /usr/bin/printf '%s\n' \
    '[req]' \
    'prompt = no' \
    'distinguished_name = subject' \
    'x509_extensions = extensions' \
    '' \
    '[subject]' \
    "CN = ${IDENTITY_NAME}" \
    'O = Froganize Local Development' \
    '' \
    '[extensions]' \
    'basicConstraints = critical, CA:FALSE' \
    'keyUsage = critical, digitalSignature' \
    'extendedKeyUsage = 1.3.6.1.5.5.7.3.3' \
    'subjectKeyIdentifier = hash' \
    'authorityKeyIdentifier = keyid,issuer'
} >"${OPENSSL_CONFIG}"

/usr/bin/openssl genrsa -out "${PRIVATE_KEY}" 3072
/usr/bin/openssl req \
  -new \
  -x509 \
  -sha256 \
  -days "${VALID_DAYS}" \
  -set_serial "0x$(/usr/bin/openssl rand -hex 16)" \
  -key "${PRIVATE_KEY}" \
  -out "${CERTIFICATE}" \
  -config "${OPENSSL_CONFIG}"
CREATED_FINGERPRINT="$(/usr/bin/openssl x509 -in "${CERTIFICATE}" -noout -fingerprint -sha1 | /usr/bin/sed -E 's/^.*=//; s/://g')"
if [[ ! "${CREATED_FINGERPRINT}" =~ '^[0-9A-Fa-f]{40}$' ]]; then
  fail 'could not determine the generated certificate fingerprint.'
fi

# add-trusted-cert both imports the certificate and limits its trust purpose to
# code signing. Importing the private key separately avoids a PKCS#12 password
# on the process command line. Never replace -T with the unsafe -A flag.
/usr/bin/security add-trusted-cert \
  -r trustRoot \
  -p codeSign \
  -k "${KEYCHAIN_PATH}" \
  "${CERTIFICATE}"
CERTIFICATE_IMPORTED=1
/usr/bin/security import "${PRIVATE_KEY}" \
  -k "${KEYCHAIN_PATH}" \
  -x \
  -T /usr/bin/codesign

IDENTITIES="$(/usr/bin/security find-identity -v -p codesigning "${KEYCHAIN_PATH}" 2>&1)"
MATCHING_LINE="$(/usr/bin/printf '%s\n' "${IDENTITIES}" | /usr/bin/grep -F -- "\"${IDENTITY_NAME}\"" | /usr/bin/head -n 1 || true)"
FINGERPRINT="$(/usr/bin/printf '%s\n' "${MATCHING_LINE}" | /usr/bin/sed -E 's/^[[:space:]]*[0-9]+\) ([0-9A-Fa-f]{40}) .*/\1/')"
if [[ ! "${FINGERPRINT}" =~ '^[0-9A-Fa-f]{40}$' ]]; then
  fail "the certificate was imported, but security did not report it as a valid code-signing identity; inspect '${IDENTITY_NAME}' in Keychain Access before retrying."
fi
if [[ "${FINGERPRINT:u}" != "${CREATED_FINGERPRINT:u}" ]]; then
  fail 'macOS reported a different code-signing identity than the certificate created by this run.'
fi
CERTIFICATE_IMPORTED=0

/usr/bin/printf '%s\n' \
  '' \
  'Local signing identity created and recognized.' \
  "Name: ${IDENTITY_NAME}" \
  "SHA-1: ${FINGERPRINT}" \
  '' \
  'Use the unambiguous SHA-1 value for future local builds:' \
  "  export FROGANIZE_LOCAL_CODESIGN_IDENTITY='${FINGERPRINT}'" \
  '  ./scripts/build_unified_macos_prototype.sh' \
  '' \
  'Do not set FROGANIZE_CODESIGN_IDENTITY at the same time.'
