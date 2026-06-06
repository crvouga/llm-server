#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

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
  brew install --cask tailscale
}

ensure_ssh_client() {
  if need_cmd ssh; then
    return
  fi

  echo "OpenSSH client missing unexpectedly. Install Xcode command line tools." >&2
  exit 1
}

print_next_steps() {
  cat <<'EOF'
Next steps on your Mac:
1) Open Tailscale and sign in to the SAME account as the Linux machine:
   open -a Tailscale

2) Find your Linux host in Tailscale:
   tailscale status

3) Connect:
   ssh <linux-username>@<hostname-or-tailscale-ip>

Optional: add a helper alias in your shell profile:
   alias llm-target='ssh <linux-username>@<hostname-or-tailscale-ip>'
EOF
}

main() {
  ensure_homebrew
  ensure_tailscale
  ensure_ssh_client
  print_next_steps
}

main "$@"
