#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is for Linux (the headless target) only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/remote-access-common.sh
source "${SCRIPT_DIR}/lib/remote-access-common.sh"

NOMACHINE_VERSION="${NOMACHINE_VERSION:-9.6.3_1}"
NOMACHINE_SERIES="${NOMACHINE_SERIES:-9.6}"
INSTALL_UBUNTU_DESKTOP=false
WRITE_DOC_ONLY=false

usage() {
  cat <<EOF
Usage: sudo $0 [OPTIONS]

Install NoMachine server for remote keyboard/mouse/display control over Tailscale.

Options:
  --with-ubuntu-desktop  Install ubuntu-desktop-minimal if no GUI is present
  --write-doc-only       Regenerate REMOTE-ACCESS.md only
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
      # ARM64 packages live under Arm/, not Linux/ (Linux/arm64 URL returns HTML).
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
      echo "Download failed: ${deb_file} is not a Debian package (got HTML or an error page)." >&2
      echo "Try setting NOMACHINE_VERSION / NOMACHINE_SERIES or install from https://www.nomachine.com/download" >&2
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
    echo "Installing ubuntu-desktop-minimal (real Ubuntu GNOME session)..."
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
  echo "  URL: ${deb_url}"
  if ! curl -fsSL "${deb_url}" -o "${tmp_deb}"; then
    echo "Failed to download NoMachine package." >&2
    exit 1
  fi
  if ! validate_deb_package "${tmp_deb}"; then
    exit 1
  fi

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
    echo "ufw not installed; skipping firewall rule (Tailscale still provides network isolation)."
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
  echo "===== NOMACHINE STATUS ====="
  if [[ -x /usr/NX/bin/nxserver ]]; then
    /usr/NX/bin/nxserver --version 2>/dev/null || true
  fi
  systemctl --no-pager --full status nxserver 2>/dev/null | sed -n '1,10p' || true
  echo
  ss -ltnp 2>/dev/null | rg ':4000' || true
}

main() {
  if [[ "${WRITE_DOC_ONLY}" == "true" ]]; then
    remote_access_write_md
    exit 0
  fi

  echo "Installing NoMachine server (remote desktop)..."
  maybe_install_ubuntu_desktop
  install_nomachine
  echo "Enabling NoMachine..."
  enable_nomachine || exit 1
  echo "Configuring firewall (Tailscale interface only)..."
  configure_firewall
  show_status
  echo "Updating REMOTE-ACCESS.md..."
  remote_access_write_md

  cat <<EOF

NoMachine is ready.

From your Mac:
  1) Pull the updated REMOTE-ACCESS.md from this repo.
  2) Run: ./scripts/setup-mac-nomachine.sh
  3) Open NoMachine and connect to: $(remote_access_tailscale_fqdn || echo '<tailscale-hostname>')

Use your Linux login password when prompted.
EOF
}

main "$@"
