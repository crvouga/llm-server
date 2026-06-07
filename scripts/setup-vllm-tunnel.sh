#!/usr/bin/env bash
# Configure Cloudflare tunnel routes for vLLM (port 8000 → vllm.chrisvouga.dev).
# Idempotent — safe to re-run. Does not start vLLM; use `make run` for the full stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CF_TUNNEL_NAME="${CF_TUNNEL_NAME:-spark-serve}"
export CF_TUNNEL_HOSTNAME="${CF_TUNNEL_HOSTNAME:-vllm.chrisvouga.dev}"

echo "Configuring tunnel '${CF_TUNNEL_NAME}' → https://${CF_TUNNEL_HOSTNAME} ..."
PYTHONUNBUFFERED=1 python3 "${ROOT}/server/server.py" --setup-tunnel
