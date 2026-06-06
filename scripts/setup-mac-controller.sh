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

  echo "OpenSSH client missing unexpectedly. Install Xcode command line tools." >&2
  exit 1
}

ensure_helper_tools() {
  if ! need_cmd nc; then
    echo "Note: 'nc' (netcat) is used by verify-mac-remote-access.sh; install via Xcode CLT if missing."
  fi
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

2) Verify connectivity:
     ./scripts/verify-mac-remote-access.sh

3) Connect via SSH:
EOF

  if [[ -n "${target_fqdn}" && "${target_fqdn}" != "<tailscale-hostname>" ]]; then
    echo "     ssh ${login_user}@${target_fqdn}"
    echo
    echo "Optional alias for ~/.zshrc:"
    echo "     alias llm-target='ssh ${login_user}@${target_fqdn}'"
  else
    echo "     ssh <linux-user>@<tailscale-hostname>   # see REMOTE-ACCESS.md"
  fi

  cat <<EOF

4) For keyboard/mouse GUI control, also run:
     ./scripts/setup-mac-nomachine.sh
EOF
}

main() {
  ensure_homebrew
  ensure_tailscale
  ensure_ssh_client
  ensure_helper_tools
  print_connection_hints
}

main "$@"
