#!/usr/bin/env python3
"""
spark_serve — Atlas (default) / vLLM + Cloudflare Tunnel for DGX Spark / GB10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Thin entrypoint. All logic lives in the `spark/` package (one small module per
concern); start with `spark/app.py` to follow the boot order.

Default engine:  Atlas (Qwen3.6-35B-A3B-FP8) — set ENGINE=vllm for the legacy path.

Idempotent. Manages its own process group. Ctrl+C or `make server-stop` stops
the tunnel and launcher but leaves the engine container running for fast restart.
Use `make server-stop-hard` to stop the container too.

Usage:
    python3 server/server.py                  # run the server
    python3 server/server.py --stop           # stop tunnel only (engine stays warm)
    python3 server/server.py --stop-hard      # stop tunnel + engine container
    python3 server/server.py --setup-tunnel   # configure DNS/ingress only
    python3 server/server.py --clear-compile-cache

Secrets via Doppler CLI (`doppler login` + `doppler setup`) or DOPPLER_TOKEN.
Doppler secrets (project=personal, config=dev):
    CLOUDFLARE_API_TOKEN   — Cloudflare API token (required; tunnels, WAF, Workers)
    CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID (required)
    HF_TOKEN               — Hugging Face token (optional)
"""

import sys
from pathlib import Path

# Allow `python3 server/server.py` from any cwd to import the spark package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spark.app import dispatch  # noqa: E402

if __name__ == "__main__":
    dispatch(sys.argv[1:])
