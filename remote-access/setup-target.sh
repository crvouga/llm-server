#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is for Linux (the headless target) only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

NOMACHINE_VERSION="${NOMACHINE_VERSION:-9.6.3_1}"
NOMACHINE_SERIES="${NOMACHINE_SERIES:-9.6}"
INSTALL_UBUNTU_DESKTOP=false
WRITE_DOC_ONLY=false

usage() {
  cat <<EOF
Usage: sudo $0 [OPTIONS]

Configure this Linux machine for remote control from a Mac (SSH + Tailscale + NoMachine).

Options:
  --with-ubuntu-desktop  Install ubuntu-desktop-minimal if no GUI is present
  --write-doc-only       Regenerate remote-access/REMOTE-ACCESS.md only
  -h, --help             Show this help
EOF
}

for arg in "$@"; do
  case "${arg}" in
    --with-ubuntu-desktop) INSTALL_UBUNTU_DESKTOP=true ;;
    --write-doc-only) WRITE_DOC_ONLY=true ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "${EUID}" -ne 0 && "${WRITE_DOC_ONLY}" == "false" ]]; then
  echo "Run this script as root (use sudo)." >&2
  exit 1
fi

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

nomachine_installed() {
  [[ -x /usr/NX/bin/nxserver ]] || dpkg -s nomachine >/dev/null 2>&1
}

detect_deb_arch() {
  local machine
  machine="$(uname -m)"
  case "${machine}" in
    x86_64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    armv7l) echo "armhf" ;;
    *)
      echo "Unsupported architecture for NoMachine: ${machine}" >&2
      exit 1
      ;;
  esac
}

nomachine_deb_url() {
  local deb_arch="$1"
  case "${deb_arch}" in
    amd64)
      echo "https://download.nomachine.com/download/${NOMACHINE_SERIES}/Linux/nomachine_${NOMACHINE_VERSION}_${deb_arch}.deb"
      ;;
    arm64)
      echo "https://download.nomachine.com/download/${NOMACHINE_SERIES}/Arm/nomachine_${NOMACHINE_VERSION}_${deb_arch}.deb"
      ;;
    armhf)
      echo "https://www.nomachine.com/free/arm/v7/deb"
      ;;
  esac
}

validate_deb_package() {
  local deb_file="$1"
  if [[ ! -s "${deb_file}" ]]; then
    echo "Download failed: ${deb_file} is empty." >&2
    return 1
  fi
  if need_cmd file; then
    file -b "${deb_file}" | rg -q 'Debian binary package' || {
      echo "Download failed: ${deb_file} is not a Debian package." >&2
      return 1
    }
  else
    [[ "$(head -c 8 "${deb_file}")" == "!<arch>"* ]] || {
      echo "Download failed: ${deb_file} is not a Debian package." >&2
      return 1
    }
  fi
  return 0
}

maybe_install_ubuntu_desktop() {
  if [[ "${INSTALL_UBUNTU_DESKTOP}" != "true" ]]; then
    return
  fi
  if need_cmd apt-get; then
    echo "Installing ubuntu-desktop-minimal..."
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ubuntu-desktop-minimal
  else
    echo "Skipping ubuntu-desktop-minimal (apt-get not available)." >&2
  fi
}

install_nomachine() {
  local deb_arch deb_url tmp_deb
  if nomachine_installed; then
    echo "NoMachine already installed."
    return 0
  fi
  if ! need_cmd apt-get; then
    echo "Automatic NoMachine install supports Debian/Ubuntu (.deb) only." >&2
    echo "Install manually from https://www.nomachine.com/download" >&2
    exit 1
  fi

  deb_arch="$(detect_deb_arch)"
  deb_url="$(nomachine_deb_url "${deb_arch}")"
  tmp_deb="$(mktemp /tmp/nomachine.XXXXXX.deb)"
  trap 'rm -f "${tmp_deb}"' RETURN

  echo "Downloading NoMachine ${NOMACHINE_VERSION} (${deb_arch})..."
  curl -fsSL "${deb_url}" -o "${tmp_deb}"
  validate_deb_package "${tmp_deb}"

  echo "Installing NoMachine..."
  if ! dpkg -i "${tmp_deb}"; then
    apt-get install -f -y
    dpkg -i "${tmp_deb}" || {
      echo "NoMachine installation failed." >&2
      exit 1
    }
  fi

  if ! nomachine_installed; then
    echo "NoMachine installation did not complete successfully." >&2
    exit 1
  fi
  echo "NoMachine installed successfully."
}

configure_firewall() {
  if ! need_cmd ufw; then
    echo "ufw not installed; skipping firewall rule."
    return
  fi
  if ufw status | rg -q 'Status: active'; then
    ufw allow in on tailscale0 to any port 4000 proto tcp comment 'nomachine over tailscale' \
      >/dev/null 2>&1 || true
    echo "Allowed NoMachine (4000) on tailscale0 via ufw."
  else
    echo "ufw inactive; no firewall changes applied."
  fi
}

enable_nomachine() {
  if ! nomachine_installed; then
    echo "NoMachine is not installed; skipping service enable." >&2
    return 1
  fi
  if systemctl list-unit-files | rg -q '^nxserver\.service'; then
    systemctl enable --now nxserver
  elif [[ -x /etc/NX/nxserver ]]; then
    /etc/NX/nxserver --restart >/dev/null 2>&1 || true
  fi
}

show_status() {
  echo
  echo "===== STATUS ====="
  systemctl --no-pager --full status tailscaled 2>/dev/null | sed -n '1,8p' || true
  systemctl --no-pager --full status ssh 2>/dev/null | sed -n '1,8p' || true
  systemctl --no-pager --full status sshd 2>/dev/null | sed -n '1,8p' || true
  echo
  tailscale status || true
  echo
  if nomachine_installed; then
    echo "===== NOMACHINE ====="
    if [[ -x /usr/NX/bin/nxserver ]]; then
      /usr/NX/bin/nxserver --version 2>/dev/null || true
    fi
    systemctl --no-pager --full status nxserver 2>/dev/null | sed -n '1,10p' || true
    ss -ltnp 2>/dev/null | rg ':4000' || true
  fi
  echo
  echo "Hostname: $(hostname)"
  echo "User accounts (for ssh login):"
  awk -F: '$3 >= 1000 && $1 != "nobody" {print " - " $1}' /etc/passwd || true
}

main() {
  if [[ "${WRITE_DOC_ONLY}" == "true" ]]; then
    remote_access_write_md
    exit 0
  fi

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
  echo "Installing NoMachine..."
  maybe_install_ubuntu_desktop
  install_nomachine
  echo "Enabling NoMachine..."
  enable_nomachine || exit 1
  echo "Configuring firewall..."
  configure_firewall
  show_status
  echo "Writing connection instructions..."
  remote_access_write_md

  cat <<EOF

Target setup complete.

Next steps:
1) Commit the generated handoff doc:
     git add remote-access/REMOTE-ACCESS.md && git commit -m "Add remote access instructions" && git push
2) On your Mac, pull the repo and run:
     ./remote-access/setup-controller.sh
3) Connect via SSH or NoMachine (see remote-access/REMOTE-ACCESS.md).
EOF
}

main "$@"
