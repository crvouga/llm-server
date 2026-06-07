#!/usr/bin/env bash
#
# ensure-remote-access.sh
# Idempotently ensures Tailscale, OpenSSH, and NoMachine are installed,
# enabled, and running on a Debian/Ubuntu Linux host. Safe to re-run.
#
# Usage:
#   sudo ./ensure-remote-access.sh
#
# Secrets are pulled from Doppler (not passed as plaintext env vars):
#   CLOUDFLARE_API_TOKEN  - API token (Account → Cloudflare Tunnel → Edit; Zone:Read for DNS).
#   CLOUDFLARE_ACCOUNT_ID - Cloudflare account id.
#   CF_TUNNEL_NAME        - Optional tunnel name (default: remote-access).
#
# Doppler access (provide ONE of these so the CLI can read the secrets):
#   DOPPLER_TOKEN     - A Doppler service token scoped to the project/config.
#   ...or a pre-configured `doppler setup` / `doppler login` on the host.
#   DOPPLER_PROJECT   - Doppler project (optional; omit if the token is scoped).
#   DOPPLER_CONFIG    - Doppler config, e.g. "dev" / "prd" (optional, same caveat).
#
# Optional environment variables (non-secret):
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
# 0. Secrets via Doppler
# ----------------------------------------------------------------------------
log "Ensuring Doppler CLI and loading secrets..."
if ! command -v doppler >/dev/null 2>&1; then
  curl -fsSL https://cli.doppler.com/install.sh | sh
  ok "Installed Doppler CLI."
else
  ok "Doppler CLI already installed."
fi

# Scope flags are added only when explicitly provided, so a service token
# (DOPPLER_TOKEN) or an existing `doppler setup` can supply project/config.
DOPPLER_ARGS=()
[ -n "${DOPPLER_PROJECT:-}" ] && DOPPLER_ARGS+=(--project "${DOPPLER_PROJECT}")
[ -n "${DOPPLER_CONFIG:-}"  ] && DOPPLER_ARGS+=(--config  "${DOPPLER_CONFIG}")

doppler_secret() {
  # Prints the secret value, or empty string if missing/unreadable.
  doppler secrets get "$1" --plain ${DOPPLER_ARGS[@]+"${DOPPLER_ARGS[@]}"} 2>/dev/null || true
}

if doppler secrets ${DOPPLER_ARGS[@]+"${DOPPLER_ARGS[@]}"} >/dev/null 2>&1; then
  ok "Doppler authenticated."
else
  warn "Doppler not authenticated/scoped. Set DOPPLER_TOKEN (and optionally"
  warn "  DOPPLER_PROJECT/DOPPLER_CONFIG), or run 'doppler login && doppler setup'."
fi

TS_AUTHKEY="$(doppler_secret TAILSCALE_AUTHKEY)"
CF_TUNNEL_NAME="${CF_TUNNEL_NAME:-remote-access}"
[ -n "${TS_AUTHKEY}" ] && ok "Loaded TAILSCALE_AUTHKEY from Doppler." \
  || warn "TAILSCALE_AUTHKEY not found in Doppler."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/cloudflare-api.sh
source "${SCRIPT_DIR}/scripts/lib/cloudflare-api.sh"

CLOUDFLARE_TUNNEL_TOKEN=""
if load_cloudflare_secrets; then
  ok "Loaded CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID from Doppler."
  if TUNNEL_ID="$(cf_ensure_tunnel "${CF_TUNNEL_NAME}")"; then
    if CLOUDFLARE_TUNNEL_TOKEN="$(cf_tunnel_connector_token "${TUNNEL_ID}")"; then
      ok "Resolved tunnel connector token via API."
    else
      warn "Could not fetch tunnel connector token via API."
    fi
  else
    warn "Could not ensure Cloudflare tunnel '${CF_TUNNEL_NAME}' via API."
  fi
else
  warn "CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID not found in Doppler."
fi

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
# 4. Cloudflare Tunnel (cloudflared)
# ----------------------------------------------------------------------------
log "Ensuring Cloudflare Tunnel (cloudflared)..."
if ! command -v cloudflared >/dev/null 2>&1; then
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflared
  ok "Installed cloudflared."
else
  ok "cloudflared already installed."
fi

# The systemd unit is created either by `cloudflared service install <TOKEN>`
# (remotely-managed tunnel) or by a local /etc/cloudflared/config.yml.
if systemctl list-unit-files | grep -q '^cloudflared\.service'; then
  ok "cloudflared service already installed."
elif [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  log "Installing cloudflared service from token..."
  cloudflared service install "${CLOUDFLARE_TUNNEL_TOKEN}"
  ok "Installed cloudflared service."
elif [ -f /etc/cloudflared/config.yml ]; then
  log "Found /etc/cloudflared/config.yml; installing service from it..."
  cloudflared service install
  ok "Installed cloudflared service from config.yml."
else
  warn "cloudflared installed but no tunnel configured."
  warn "  -> Set CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID in Doppler and re-run,"
  warn "     or place a config at /etc/cloudflared/config.yml first."
fi

if systemctl list-unit-files | grep -q '^cloudflared\.service'; then
  systemctl enable cloudflared >/dev/null 2>&1 || true
  systemctl start  cloudflared >/dev/null 2>&1 || true
  systemctl is-active --quiet cloudflared \
    && ok "cloudflared is active." \
    || warn "cloudflared not active; check: journalctl -u cloudflared -n 50"
fi

# ----------------------------------------------------------------------------
# 5. Firewall (only touch ufw if it's active)
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
# 6. Summary
# ----------------------------------------------------------------------------
echo
log "==================== SUMMARY ===================="
systemctl is-active --quiet "$SSH_UNIT"  && ok "SSH: active"        || warn "SSH: NOT active"
systemctl is-active --quiet tailscaled   && ok "tailscaled: active" || warn "tailscaled: NOT active"
systemctl is-active --quiet cloudflared  && ok "cloudflared: active" || warn "cloudflared: NOT active/configured"
TS_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
[ -n "$TS_IP" ] && ok "Tailscale IP: ${TS_IP}" || warn "No Tailscale IPv4 yet."
[ -x /usr/NX/bin/nxserver ] && ok "NoMachine: installed" || warn "NoMachine: not installed"
echo
ok "Done. From your Mac, test with:"
echo "    tailscale ping ${TS_IP:-<this-host-ip>}"
echo "    ssh <user>@${TS_IP:-<this-host-ip>}        # or: tailscale ssh <user>@<hostname>"