#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

VERIFY_ONLY=false

for arg in "$@"; do
  case "${arg}" in
    --verify-only) VERIFY_ONLY=true ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--verify-only]

Set up this Mac to control a remote Linux machine (Tailscale + SSH + NoMachine).

Options:
  --verify-only  Skip installs; only run connectivity checks
  -h, --help     Show this help
EOF
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

ensure_homebrew() {
  if need_cmd brew; then
    return
  fi
  echo "Homebrew not found. Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
}

ensure_tailscale() {
  if [[ -d "/Applications/Tailscale.app" ]]; then
    echo "Tailscale app already installed."
    return
  fi
  echo "Installing Tailscale..."
  brew install --cask tailscale-app
}

ensure_ssh_client() {
  if need_cmd ssh; then
    return
  fi
  echo "OpenSSH client missing. Install Xcode command line tools." >&2
  exit 1
}

ensure_nomachine_client() {
  if [[ -d "/Applications/NoMachine.app" ]]; then
    echo "NoMachine already installed."
    return
  fi
  echo "Installing NoMachine..."
  brew install --cask nomachine
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
    echo "remote-access/REMOTE-ACCESS.md not found at ${md_file}" >&2
    echo "Pull the repo after running setup-target.sh on the Linux machine." >&2
    return 1
  fi
  TARGET_USER="$(remote_access_parse_md_field "Login user" "${md_file}")"
  TARGET_FQDN="$(remote_access_parse_md_field "Tailscale DNS name" "${md_file}")"
  TARGET_IP="$(remote_access_parse_md_field "Tailscale IPv4" "${md_file}")"
  [[ -n "${TARGET_USER}" && -n "${TARGET_FQDN}" ]]
}

verify_connectivity() {
  local failures=0

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

  check_ping() {
    [[ -n "${TARGET_IP:-}" && "${TARGET_IP}" != "<tailscale-ip>" ]]
    ping -c 1 -t 3 "${TARGET_IP}" >/dev/null 2>&1
  }

  check_ssh() {
    [[ -n "${TARGET_USER:-}" && -n "${TARGET_FQDN:-}" ]]
    ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      "${TARGET_USER}@${TARGET_FQDN}" 'hostname' >/dev/null 2>&1
  }

  check_nomachine_port() {
    [[ -n "${TARGET_FQDN:-}" ]]
    nc -z -G 5 "${TARGET_FQDN}" 4000 >/dev/null 2>&1
  }

  echo
  echo "Verifying Mac -> target remote access"
  echo

  check "Tailscale CLI" check_tailscale_cli
  check "Tailscale connected" check_tailscale_running

  if load_target_from_md; then
    echo "Target from REMOTE-ACCESS.md: ${TARGET_USER}@${TARGET_FQDN} (${TARGET_IP})"
    echo
    check "ICMP to target" check_ping
    check "SSH to target" check_ssh
    check "NoMachine port 4000" check_nomachine_port
  else
    failures=$((failures + 1))
  fi

  echo
  if [[ "${failures}" -eq 0 ]]; then
    echo "All checks passed."
    return 0
  fi

  echo "${failures} check(s) failed. See remote-access/REMOTE-ACCESS.md for setup steps." >&2
  return 1
}

print_connection_hints() {
  local md_file login_user target_fqdn
  md_file="$(remote_access_output_file)"

  if [[ -f "${md_file}" ]]; then
    login_user="$(remote_access_parse_md_field "Login user" "${md_file}" || true)"
    target_fqdn="$(remote_access_parse_md_field "Tailscale DNS name" "${md_file}" || true)"
  fi

  cat <<EOF

Next steps on your Mac:
1) Open Tailscale and sign in to the SAME account as the Linux machine:
     open -a Tailscale

2) Connect via SSH:
EOF

  if [[ -n "${target_fqdn}" && "${target_fqdn}" != "<tailscale-hostname>" ]]; then
    echo "     ssh ${login_user}@${target_fqdn}"
    echo
    echo "Optional alias for ~/.zshrc:"
    echo "     alias llm-target='ssh ${login_user}@${target_fqdn}'"
  else
    echo "     ssh <linux-user>@<tailscale-hostname>   # see remote-access/REMOTE-ACCESS.md"
  fi

  cat <<EOF

3) For keyboard/mouse GUI control:
     open -a NoMachine
EOF

  if [[ -n "${target_fqdn}" && "${target_fqdn}" != "<tailscale-hostname>" ]]; then
    cat <<EOF
     Host: ${target_fqdn}
     Port: 4000
     User: ${login_user:-<linux-login-user>}
EOF
  fi
}

main() {
  if [[ "${VERIFY_ONLY}" == "true" ]]; then
    verify_connectivity
    exit $?
  fi

  ensure_homebrew
  ensure_tailscale
  ensure_ssh_client
  ensure_nomachine_client
  print_connection_hints
  verify_connectivity || true
}

main "$@"
