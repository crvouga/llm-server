#!/usr/bin/env bash
#
# ensure-remote-access.sh
# Idempotently ensures Tailscale, OpenSSH, and NoMachine are installed,
# enabled, and running on a Debian/Ubuntu Linux host. Safe to re-run.
#
# Usage:
#   sudo ./ensure-remote-access.sh
#
# Optional environment variables:
#   TS_AUTHKEY        - Tailscale auth key (tskey-...) for unattended re-auth.
#   TS_HOSTNAME       - Override the tailnet hostname (defaults to system hostname).
#   NOMACHINE_DEB_URL - Direct URL to the NoMachine .deb for THIS arch.
#                       Get it from https://www.nomachine.com/download
#   SSH_PASSWORD_AUTH - "yes" or "no" (default: leave existing config untouched).

set -euo pipefail

log()  { printf '\033[1;34m[*]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."
command -v apt-get >/dev/null 2>&1 || die "This script targets Debian/Ubuntu (apt-get not found)."

ARCH="$(dpkg --print-architecture)"
log "Host: $(hostname)  Arch: ${ARCH}  Kernel: $(uname -r)"

# ----------------------------------------------------------------------------
# 1. OpenSSH server
# ----------------------------------------------------------------------------
log "Ensuring OpenSSH server..."
if ! dpkg -s openssh-server >/dev/null 2>&1; then
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
  ok "Installed openssh-server."
else
  ok "openssh-server already installed."
fi

# Service unit is 'ssh' on Debian/Ubuntu, 'sshd' on some others.
SSH_UNIT="ssh"
systemctl list-unit-files | grep -q '^ssh\.service' || SSH_UNIT="sshd"

systemctl enable "$SSH_UNIT" >/dev/null 2>&1 || true
systemctl start  "$SSH_UNIT" >/dev/null 2>&1 || true

# Optionally enforce password auth setting only if explicitly requested.
if [ "${SSH_PASSWORD_AUTH:-}" = "yes" ] || [ "${SSH_PASSWORD_AUTH:-}" = "no" ]; then
  DROPIN=/etc/ssh/sshd_config.d/99-remote-access.conf
  mkdir -p /etc/ssh/sshd_config.d
  desired="PasswordAuthentication ${SSH_PASSWORD_AUTH}"
  if [ ! -f "$DROPIN" ] || ! grep -qxF "$desired" "$DROPIN"; then
    printf '%s\n' "$desired" > "$DROPIN"
    sshd -t && systemctl reload "$SSH_UNIT"
    ok "Set ${desired}."
  fi
fi
systemctl is-active --quiet "$SSH_UNIT" && ok "SSH (${SSH_UNIT}) is active." || warn "SSH not active."

# ----------------------------------------------------------------------------
# 2. Tailscale
# ----------------------------------------------------------------------------
log "Ensuring Tailscale..."
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
  ok "Installed Tailscale."
else
  ok "Tailscale already installed."
fi

systemctl enable tailscaled >/dev/null 2>&1 || true
systemctl start  tailscaled >/dev/null 2>&1 || true

# Bring the tailnet up only if not already connected.
if tailscale status >/dev/null 2>&1; then
  ok "Tailscale already connected."
else
  warn "Tailscale not connected; bringing it up..."
  UP_ARGS=(--ssh --accept-routes)
  [ -n "${TS_HOSTNAME:-}" ] && UP_ARGS+=(--hostname "${TS_HOSTNAME}")
  if [ -n "${TS_AUTHKEY:-}" ]; then
    tailscale up "${UP_ARGS[@]}" --authkey "${TS_AUTHKEY}"
  else
    warn "No TS_AUTHKEY set; this may print a login URL you must open in a browser."
    tailscale up "${UP_ARGS[@]}"
  fi
fi

# --ssh enables Tailscale SSH (works even if OpenSSH is misconfigured).
tailscale set --ssh >/dev/null 2>&1 || true
tailscale status || warn "tailscale status returned non-zero."

# ----------------------------------------------------------------------------
# 3. NoMachine
# ----------------------------------------------------------------------------
log "Ensuring NoMachine..."
if [ -x /usr/NX/bin/nxserver ]; then
  ok "NoMachine already installed."
  /usr/NX/bin/nxserver --startup >/dev/null 2>&1 || true
  /usr/NX/bin/nxserver --status   || warn "nxserver status non-zero."
elif [ -n "${NOMACHINE_DEB_URL:-}" ]; then
  tmp="$(mktemp --suffix=.deb)"
  log "Downloading NoMachine from ${NOMACHINE_DEB_URL}"
  curl -fsSL "${NOMACHINE_DEB_URL}" -o "$tmp"
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$tmp"
  rm -f "$tmp"
  ok "Installed NoMachine."
  /usr/NX/bin/nxserver --startup >/dev/null 2>&1 || true
else
  warn "NoMachine not installed and NOMACHINE_DEB_URL not set."
  warn "  -> Get the .deb for arch '${ARCH}' from https://www.nomachine.com/download"
  warn "  -> Then re-run: sudo NOMACHINE_DEB_URL='https://...deb' $0"
fi

# ----------------------------------------------------------------------------
# 4. Firewall (only touch ufw if it's active)
# ----------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  log "ufw active; ensuring required ports allowed..."
  ufw allow 22/tcp        >/dev/null 2>&1 || true   # SSH
  ufw allow 4000/tcp      >/dev/null 2>&1 || true   # NoMachine NX
  ufw allow in on tailscale0 >/dev/null 2>&1 || true # all tailnet traffic
  ok "ufw rules ensured."
else
  ok "ufw inactive or absent; skipping firewall changes."
fi

# ----------------------------------------------------------------------------
# 5. Summary
# ----------------------------------------------------------------------------
echo
log "==================== SUMMARY ===================="
systemctl is-active --quiet "$SSH_UNIT"  && ok "SSH: active"        || warn "SSH: NOT active"
systemctl is-active --quiet tailscaled   && ok "tailscaled: active" || warn "tailscaled: NOT active"
TS_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
[ -n "$TS_IP" ] && ok "Tailscale IP: ${TS_IP}" || warn "No Tailscale IPv4 yet."
[ -x /usr/NX/bin/nxserver ] && ok "NoMachine: installed" || warn "NoMachine: not installed"
echo
ok "Done. From your Mac, test with:"
echo "    tailscale ping ${TS_IP:-<this-host-ip>}"
echo "    ssh <user>@${TS_IP:-<this-host-ip>}        # or: tailscale ssh <user>@<hostname>"