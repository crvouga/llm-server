#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/remote-access-common.sh
source "${SCRIPT_DIR}/lib/remote-access-common.sh"

CHECK_DESKTOP=false
for arg in "$@"; do
  case "${arg}" in
    --desktop) CHECK_DESKTOP=true ;;
    -h|--help)
      echo "Usage: $0 [--desktop]"
      echo "  --desktop  also verify xrdp port 3389 on the target"
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      exit 1
      ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

failures=0

check() {
  local label="$1"
  shift
  echo -n "Checking ${label}... "
  if "$@"; then
    echo "OK"
  else
    echo "FAILED"
    failures=$((failures + 1))
  fi
}

check_tailscale_cli() {
  if need_cmd tailscale; then
    return 0
  fi
  if [[ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
    export PATH="/Applications/Tailscale.app/Contents/MacOS:${PATH}"
    need_cmd tailscale
    return $?
  fi
  return 1
}

check_tailscale_running() {
  check_tailscale_cli
  tailscale status >/dev/null 2>&1
}

load_target_from_md() {
  local md_file
  md_file="$(remote_access_output_file)"
  if [[ ! -f "${md_file}" ]]; then
    echo "REMOTE-ACCESS.md not found at ${md_file}" >&2
    return 1
  fi
  TARGET_USER="$(remote_access_parse_md_field "Login user" "${md_file}")"
  TARGET_FQDN="$(remote_access_parse_md_field "Tailscale DNS name" "${md_file}")"
  TARGET_IP="$(remote_access_parse_md_field "Tailscale IPv4" "${md_file}")"
  [[ -n "${TARGET_USER}" && -n "${TARGET_FQDN}" ]]
}

check_ping() {
  [[ -n "${TARGET_IP:-}" && "${TARGET_IP}" != "<tailscale-ip>" ]]
  ping -c 1 -t 3 "${TARGET_IP}" >/dev/null 2>&1
}

check_ssh() {
  [[ -n "${TARGET_USER:-}" && -n "${TARGET_FQDN:-}" ]]
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
    "${TARGET_USER}@${TARGET_FQDN}" 'hostname' >/dev/null 2>&1
}

check_rdp_port() {
  [[ -n "${TARGET_FQDN:-}" ]]
  nc -z -G 5 "${TARGET_FQDN}" 3389 >/dev/null 2>&1
}

main() {
  echo "Verifying Mac -> target remote access"
  echo

  check "Tailscale CLI" check_tailscale_cli
  check "Tailscale connected" check_tailscale_running

  if load_target_from_md; then
    echo "Target from REMOTE-ACCESS.md: ${TARGET_USER}@${TARGET_FQDN} (${TARGET_IP})"
    echo
    check "ICMP to target" check_ping
    check "SSH to target" check_ssh
    if [[ "${CHECK_DESKTOP}" == "true" ]]; then
      check "xrdp port 3389" check_rdp_port
    fi
  else
    echo "Could not load target details from REMOTE-ACCESS.md" >&2
    failures=$((failures + 1))
  fi

  echo
  if [[ "${failures}" -eq 0 ]]; then
    echo "All checks passed."
    exit 0
  fi

  echo "${failures} check(s) failed. See REMOTE-ACCESS.md for setup steps." >&2
  exit 1
}

main "$@"
