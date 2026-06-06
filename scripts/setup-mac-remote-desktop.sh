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

ensure_remote_desktop_client() {
  if [[ -d "/Applications/Windows App.app" ]] \
    || [[ -d "/Applications/Microsoft Remote Desktop.app" ]]; then
    echo "Remote desktop client already installed."
    return
  fi

  echo "Installing Microsoft Remote Desktop (Windows App)..."
  brew install --cask microsoft-remote-desktop
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

Remote desktop client setup complete.

Next steps:
1) Ensure Tailscale is running and signed in:
     open -a Tailscale

2) Open Microsoft Remote Desktop:
     open -a "Windows App" 2>/dev/null || open -a "Microsoft Remote Desktop"

3) Add a PC with these values from REMOTE-ACCESS.md:
EOF

  if [[ -n "${target_fqdn}" && "${target_fqdn}" != "<tailscale-hostname>" ]]; then
    cat <<EOF
     PC name:  ${target_fqdn}
     User:     ${login_user:-<linux-login-user>}
EOF
  else
    cat <<EOF
     PC name:  <tailscale-dns-name from REMOTE-ACCESS.md>
     User:     <linux-login-user from REMOTE-ACCESS.md>
EOF
  fi

  cat <<EOF

4) Verify connectivity:
     ./scripts/verify-mac-remote-access.sh --desktop

If remote desktop is not configured on the target yet, run over SSH:
     sudo ./scripts/setup-target-remote-desktop.sh
EOF
}

main() {
  ensure_homebrew
  ensure_remote_desktop_client
  print_next_steps
}

main "$@"
