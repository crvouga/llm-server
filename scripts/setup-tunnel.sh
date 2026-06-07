#!/usr/bin/env bash
# Setup Cloudflare tunnel for LM Studio (port 1234 → lm-studio.chrisvouga.dev)
# One-shot: creates tunnel via API, routes DNS, writes config, starts systemd service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/cloudflare-api.sh
source "${SCRIPT_DIR}/lib/cloudflare-api.sh"

TUNNEL_NAME="lm-studio"
HOSTNAME="lm-studio.chrisvouga.dev"
SERVICE="lm-studio-cloudflared.service"
PORT=1234

DOPPLER_PROJECT="${DOPPLER_PROJECT:-personal}"
DOPPLER_CONFIG="${DOPPLER_CONFIG:-dev}"

DOPPLER_ARGS=()
[ -n "${DOPPLER_PROJECT}" ] && DOPPLER_ARGS+=(--project "${DOPPLER_PROJECT}")
[ -n "${DOPPLER_CONFIG}" ] && DOPPLER_ARGS+=(--config "${DOPPLER_CONFIG}")

doppler_secret() {
  doppler secrets get "$1" --plain ${DOPPLER_ARGS[@]+"${DOPPLER_ARGS[@]}"} 2>/dev/null || true
}

die() { echo "Error: $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl is required."
command -v jq >/dev/null 2>&1 || die "jq is required."
command -v cloudflared >/dev/null 2>&1 || die "cloudflared not found. Run: make ensure-system-deps"
command -v doppler >/dev/null 2>&1 || die "doppler not found. Run: make ensure-system-deps"

echo "Loading Cloudflare credentials from Doppler (${DOPPLER_PROJECT}/${DOPPLER_CONFIG})..."
load_cloudflare_secrets || die "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID required (Doppler or env)."

echo "Ensuring tunnel '${TUNNEL_NAME}'..."
TUNNEL_ID="$(cf_ensure_tunnel "${TUNNEL_NAME}")" || die "Failed to ensure tunnel '${TUNNEL_NAME}' via Cloudflare API."
echo "Tunnel id: ${TUNNEL_ID}"

echo "Routing DNS for ${HOSTNAME}..."
cf_ensure_tunnel_dns "${TUNNEL_ID}" "${HOSTNAME}" || die "Failed to route DNS for '${HOSTNAME}'."

echo "Fetching connector token via API..."
CONNECTOR_TOKEN="$(cf_tunnel_connector_token "${TUNNEL_ID}")" || die "Failed to fetch tunnel connector token."

TOKEN_FILE="${HOME}/.cloudflared/${TUNNEL_NAME}.token"
install -d -m 0700 "${HOME}/.cloudflared"
printf '%s' "${CONNECTOR_TOKEN}" > "${TOKEN_FILE}"
chmod 600 "${TOKEN_FILE}"

UNIT_PATH="${HOME}/.config/systemd/user/${SERVICE}"
mkdir -p "${HOME}/.config/systemd/user"
CLOUDFLARED_BIN="$(command -v cloudflared)"
cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=Cloudflare tunnel for LM Studio
After=network.target

[Service]
Type=simple
ExecStart=/bin/sh -c 'exec ${CLOUDFLARED_BIN} tunnel --no-autoupdate run --token "$$(tr -d "\\n" < ${TOKEN_FILE})"'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
echo "Unit written to ${UNIT_PATH}"

echo "Starting service '${SERVICE}'..."
systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE}"
echo "Done. Tunnel is live at https://${HOSTNAME}"
echo "Check status: systemctl --user status ${SERVICE}"
echo "Tail logs:    journalctl --user -f -u ${SERVICE}"
