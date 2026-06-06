#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root (use sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/remote-access-common.sh
source "${SCRIPT_DIR}/lib/remote-access-common.sh"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_pkgs() {
  if need_cmd apt-get; then
    apt-get update
    apt-get install -y curl openssh-server tmux ripgrep
  elif need_cmd dnf; then
    dnf install -y curl openssh-server tmux ripgrep
  elif need_cmd pacman; then
    pacman -Sy --noconfirm curl openssh tmux ripgrep
  elif need_cmd zypper; then
    zypper --non-interactive install curl openssh tmux ripgrep
  else
    echo "Unsupported package manager. Install curl + OpenSSH server manually." >&2
    exit 1
  fi
}

install_tailscale() {
  if need_cmd tailscale && need_cmd tailscaled; then
    echo "Tailscale already installed."
    return
  fi

  curl -fsSL https://tailscale.com/install.sh | sh
}

enable_ssh_service() {
  local service_name=""
  if systemctl list-unit-files | rg -q '^ssh\.service'; then
    service_name="ssh"
  elif systemctl list-unit-files | rg -q '^sshd\.service'; then
    service_name="sshd"
  else
    echo "Could not find SSH service unit (ssh/sshd)." >&2
    exit 1
  fi

  systemctl enable --now "${service_name}"
}

enable_tailscale_service() {
  systemctl enable --now tailscaled
}

bring_up_tailscale() {
  tailscale up --ssh
}

show_status() {
  echo
  echo "===== STATUS ====="
  systemctl --no-pager --full status tailscaled | sed -n '1,8p'
  systemctl --no-pager --full status ssh 2>/dev/null | sed -n '1,8p' || true
  systemctl --no-pager --full status sshd 2>/dev/null | sed -n '1,8p' || true
  echo
  tailscale status || true
  echo
  echo "Hostname: $(hostname)"
  echo "User accounts on this box (choose one for ssh login):"
  awk -F: '$3 >= 1000 && $1 != "nobody" {print " - " $1}' /etc/passwd || true
}

main() {
  echo "Installing prerequisites..."
  install_pkgs
  echo "Installing Tailscale..."
  install_tailscale
  echo "Enabling SSH..."
  enable_ssh_service
  echo "Enabling Tailscale daemon..."
  enable_tailscale_service
  echo "Bringing Tailscale online..."
  bring_up_tailscale
  show_status
  echo "Writing connection instructions..."
  remote_access_write_md

  cat <<EOF

Next steps:
1) Optional: enable keyboard/mouse GUI access:
     sudo ./scripts/setup-target-remote-desktop.sh
2) Commit the generated instructions to git:
     git add REMOTE-ACCESS.md && git commit -m "Add remote access instructions"
     git push
3) On your Mac, pull the repo and run:
     ./scripts/setup-mac-controller.sh
     ./scripts/setup-mac-remote-desktop.sh   # if using GUI
4) Verify from the Mac:
     ./scripts/verify-mac-remote-access.sh
EOF
}

main "$@"
