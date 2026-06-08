#!/usr/bin/env python3
"""
spark_serve — vLLM + Cloudflare Tunnel for DGX Spark / GB10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Thin entrypoint. All logic lives in the `spark/` package; start with
`spark/app.py` to follow the boot order.

Target host: ASUS Ascent GX10 AI Supercomputer (DGX Spark, NVIDIA GB10 Superchip,
128 GB LPDDR5x, 1 TB PCIe Gen4 NVMe). See README.md § Hardware.

Default model: RedHatAI/Qwen3-Coder-Next-NVFP4 via vLLM (OpenAI-compatible API).
Set ENGINE=atlas for the legacy Atlas path.

Idempotent. Manages its own process group. Ctrl+C or `make server-stop` stops
the tunnel, launcher, and inference engine container.

Usage:
    python3 server/server.py                  # run the server
    python3 server/server.py --stop           # stop tunnel + engine container
    python3 server/server.py --setup-tunnel   # configure DNS/ingress only

Secrets via vault CLI (`vault login` + `vault setup --project personal --config dev`)
or VAULT_TOKEN. Secret store path (project=personal, config=dev):
    CLOUDFLARE_API_TOKEN   — Cloudflare API token (required; tunnels, WAF, Workers)
    CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID (required)
    HF_TOKEN               — Hugging Face token (optional)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spark.app import dispatch  # noqa: E402

if __name__ == "__main__":
    dispatch(sys.argv[1:])
