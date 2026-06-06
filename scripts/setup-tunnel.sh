#!/usr/bin/env bash
# Setup Cloudflare tunnel for LM Studio (port 1234 → lm-studio.chrisvouga.dev)
# One-shot: creates tunnel, routes DNS, writes config, starts systemd service.
set -euo pipefail

TUNNEL_NAME="lm-studio"
HOSTNAME="lm-studio.chrisvouga.dev"
SERVICE="lm-studio-cloudflared.service"
CONFIG_PATH="$HOME/.cloudflared/${TUNNEL_NAME}.yml"
CREDS_DIR="$HOME/.cloudflared"
PORT=1234

# --- helpers ---
resolve_tunnel_id() {
  # 1) existing tunnel by name
  local id
  id=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import sys, json
for t in json.loads(sys.stdin.read()):
    if t.get('name') == '$TUNNEL_NAME':
        print(t['id']); break
" 2>/dev/null || true)
  if [ -n "$id" ]; then echo "$id"; return; fi

  # 2) credentials file
  for f in "$CREDS_DIR"/*.json; do
    [ -f "$f" ] || continue
    id=$(python3 -c "import json; d=json.load(open('$f')); print(d.get('TunnelID',''))" 2>/dev/null || true)
    if [ -n "$id" ]; then echo "$id"; return; fi
  done
}

# --- preflight ---
if ! command -v cloudflared &>/dev/null; then
  echo "Error: cloudflared not found. Run: make ensure-system-deps"
  exit 1
fi

# --- create tunnel if needed ---
TUNNEL_ID=$(resolve_tunnel_id)
if [ -z "$TUNNEL_ID" ]; then
  echo "Creating tunnel '${TUNNEL_NAME}'..."
  cloudflared tunnel create "$TUNNEL_NAME" 2>/dev/null || true
  TUNNEL_ID=$(resolve_tunnel_id)
  if [ -z "$TUNNEL_ID" ]; then
    echo "Error: failed to create tunnel. Is cloudflared authenticated? Run: cloudflared tunnel login"
    exit 1
  fi
  echo "Tunnel created: ${TUNNEL_ID}"
else
  echo "Tunnel '${TUNNEL_NAME}' already exists: ${TUNNEL_ID}"
fi

# --- route DNS ---
echo "Routing DNS for ${HOSTNAME} → tunnel..."
cloudflared tunnel route dns "$TUNNEL_ID" "$HOSTNAME" 2>/dev/null || true

# --- write config ---
mkdir -p "$HOME/.cloudflared"
cat > "$CONFIG_PATH" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CREDS_DIR}/${TUNNEL_ID}.json
ingress:
  - hostname: ${HOSTNAME}
    service: http://127.0.0.1:${PORT}
  - service: http_status:404

# managed by scripts/setup-tunnel.sh
EOF
echo "Config written to ${CONFIG_PATH}"

# --- write systemd unit ---
UNIT_PATH="$HOME/.config/systemd/user/${SERVICE}"
mkdir -p "$HOME/.config/systemd/user"
CLOUDFLARED_BIN=$(which cloudflared)
cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Cloudflare tunnel for LM Studio
After=network.target

[Service]
Type=simple
ExecStart=${CLOUDFLARED_BIN} tunnel --config ${CONFIG_PATH} run
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
echo "Unit written to ${UNIT_PATH}"

# --- start service ---
echo "Starting service '${SERVICE}'..."
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE"
echo "Done. Tunnel is live at https://${HOSTNAME}"
echo "Check status: systemctl --user status ${SERVICE}"
echo "Tail logs:    journalctl --user -f -u ${SERVICE}"
