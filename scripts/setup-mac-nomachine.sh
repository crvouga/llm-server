#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/remote-access-common.sh
source "${SCRIPT_DIR}/lib/remote-access-common.sh"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

ensure_homebrew() {
  if need_cmd brew; then
    return
  fi
  echo "Homebrew not found. Run ./scripts/setup-mac-controller.sh first." >&2
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

read_connection_hints() {
  local md_file login_user target_fqdn
  md_file="$(remote_access_output_file)"

  if [[ ! -f "${md_file}" ]]; then
    echo "REMOTE-ACCESS.md not found. Pull the repo after running target setup." >&2
    return 1
  fi

  login_user="$(remote_access_parse_md_field "Login user" "${md_file}" || true)"
  target_fqdn="$(remote_access_parse_md_field "Tailscale DNS name" "${md_file}" || true)"

  echo "${login_user}|${target_fqdn}"
}

print_next_steps() {
  local hints login_user target_fqdn
  hints="$(read_connection_hints 2>/dev/null || echo "|")"
  login_user="${hints%%|*}"
  target_fqdn="${hints#*|}"

  cat <<EOF

NoMachine client setup complete.

Next steps:
1) Ensure Tailscale is running and signed in:
     open -a Tailscale

2) Open NoMachine:
     open -a NoMachine

3) Add / connect to your Linux machine:
EOF

  if [[ -n "${target_fqdn}" && "${target_fqdn}" != "<tailscale-hostname>" ]]; then
    cat <<EOF
     Host:  ${target_fqdn}
     Port:  4000 (default)
     User:  ${login_user:-<linux-login-user>}
EOF
  else
    cat <<EOF
     Host:  <tailscale-dns-name from REMOTE-ACCESS.md>
     Port:  4000
     User:  <linux-login-user from REMOTE-ACCESS.md>
EOF
  fi

  cat <<EOF

4) Verify connectivity:
     ./scripts/verify-mac-remote-access.sh --nomachine

If NoMachine is not configured on the target yet, run over SSH:
     sudo ./scripts/setup-target-nomachine.sh
EOF
}

main() {
  ensure_homebrew
  ensure_nomachine_client
  print_next_steps
}

main "$@"
