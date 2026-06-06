#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is for Linux (the headless target) only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/remote-access-common.sh
source "${SCRIPT_DIR}/lib/remote-access-common.sh"

WRITE_DOC_ONLY=false
if [[ "${1:-}" == "--write-doc-only" ]]; then
  WRITE_DOC_ONLY=true
fi

if [[ "${EUID}" -ne 0 && "${WRITE_DOC_ONLY}" == "false" ]]; then
  echo "Run this script as root (use sudo)." >&2
  exit 1
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_desktop_packages() {
  if need_cmd apt-get; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      xrdp xfce4 xfce4-goodies dbus-x11
  elif need_cmd dnf; then
    dnf install -y xrdp xfce4-session xfce4-panel xfce4-terminal dbus-x11
  else
    echo "Unsupported package manager. Install xrdp + XFCE manually." >&2
    exit 1
  fi
}

configure_xfce_session() {
  local login_user home_dir
  login_user="$(remote_access_resolve_login_user)"
  if [[ -z "${login_user}" ]]; then
    echo "Could not determine login user for desktop session." >&2
    exit 1
  fi

  home_dir="$(getent passwd "${login_user}" | cut -d: -f6)"
  if [[ -z "${home_dir}" || ! -d "${home_dir}" ]]; then
    echo "Home directory not found for user: ${login_user}" >&2
    exit 1
  fi

  cat >"${home_dir}/.xsession" <<'EOF'
#!/bin/sh
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE
exec startxfce4
EOF
  chmod +x "${home_dir}/.xsession"
  chown "${login_user}:${login_user}" "${home_dir}/.xsession"

  if getent group ssl-cert >/dev/null; then
    usermod -aG ssl-cert "${login_user}" 2>/dev/null || true
  fi
}

configure_firewall() {
  if ! need_cmd ufw; then
    echo "ufw not installed; skipping firewall rule (Tailscale still provides network isolation)."
    return
  fi

  if ufw status | rg -q 'Status: active'; then
    ufw allow in on tailscale0 to any port 3389 proto tcp comment 'xrdp over tailscale' \
      >/dev/null 2>&1 || true
    echo "Allowed xrdp (3389) on tailscale0 via ufw."
  else
    echo "ufw inactive; no firewall changes applied."
  fi
}

enable_xrdp() {
  systemctl enable --now xrdp
}

show_status() {
  echo
  echo "===== REMOTE DESKTOP STATUS ====="
  systemctl --no-pager --full status xrdp | sed -n '1,10p'
  echo
  ss -ltnp 2>/dev/null | rg ':3389' || true
}

main() {
  if [[ "${WRITE_DOC_ONLY}" == "true" ]]; then
    remote_access_write_md
    exit 0
  fi

  echo "Installing xrdp + XFCE (headless-friendly remote desktop)..."
  install_desktop_packages
  echo "Configuring XFCE session for login user..."
  configure_xfce_session
  echo "Enabling xrdp..."
  enable_xrdp
  echo "Configuring firewall (Tailscale interface only)..."
  configure_firewall
  show_status
  echo "Updating REMOTE-ACCESS.md..."
  remote_access_write_md

  cat <<EOF

Remote desktop is ready.

From your Mac:
  1) Pull the updated REMOTE-ACCESS.md from this repo.
  2) Run: ./scripts/setup-mac-remote-desktop.sh
  3) Connect Microsoft Remote Desktop to: $(remote_access_tailscale_fqdn || echo '<tailscale-hostname>')

Use your Linux login password when prompted.
EOF
}

main "$@"
