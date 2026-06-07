"""Fetch secrets from Doppler (env -> API -> CLI) into Config."""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from .console import die, ok, section, warn


def _apply_doppler_secrets(cfg, secrets: dict, source: str) -> None:
    def require(key):
        val = secrets.get(key, "")
        if not val:
            die(
                f"Secret '{key}' not found in Doppler {cfg.doppler_project}/{cfg.doppler_config}"
            )
        return val

    cfg.cf_api_token = secrets.get("CLOUDFLARE_API_TOKEN", "").strip()
    cfg.cf_account_id = secrets.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    cfg.cf_tunnel_token = (
        secrets.get("CF_TUNNEL_TOKEN", "")
        or secrets.get("CLOUDFLARE_TUNNEL_TOKEN", "")
    ).strip()
    cfg.hf_token = secrets.get("HF_TOKEN", "")

    ok(f"Secrets loaded from {source} ({cfg.doppler_project}/{cfg.doppler_config})")
    if not cfg.cf_api_token:
        die(
            f"Missing CLOUDFLARE_API_TOKEN in Doppler ({cfg.doppler_project}/{cfg.doppler_config}).\n"
            "  Token needs Account → Cloudflare Tunnel → Edit."
        )
    if not cfg.cf_account_id:
        die(
            f"Missing CLOUDFLARE_ACCOUNT_ID in Doppler ({cfg.doppler_project}/{cfg.doppler_config})."
        )
    ok("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID loaded")
    if cfg.cf_tunnel_token:
        warn("Using CF_TUNNEL_TOKEN override instead of fetching connector token via API")
    if not cfg.hf_token:
        warn("HF_TOKEN not in Doppler — fine for public models")


def _fetch_doppler_secrets_via_api(cfg) -> dict:
    token = cfg.doppler_token or os.environ.get("DOPPLER_TOKEN", "")
    if not token:
        return {}

    url = (
        "https://api.doppler.com/v3/configs/config/secrets/download"
        f"?project={cfg.doppler_project}&config={cfg.doppler_config}&format=json"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        die(f"Doppler API error {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        die(f"Could not reach Doppler: {e.reason}")


def _fetch_doppler_secrets_via_cli(cfg) -> dict:
    if not shutil.which("doppler"):
        return {}

    result = subprocess.run(
        [
            "doppler",
            "secrets",
            "download",
            "--project",
            cfg.doppler_project,
            "--config",
            cfg.doppler_config,
            "--no-file",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        die(
            "Could not fetch secrets via Doppler CLI.\n"
            f"  Project: {cfg.doppler_project}  Config: {cfg.doppler_config}\n"
            "  Run: doppler login && doppler setup --project personal --config dev\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def fetch_doppler_secrets(cfg):
    section("Fetching secrets from Doppler")

    if os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        _apply_doppler_secrets(cfg, os.environ, "environment")
        return

    secrets = _fetch_doppler_secrets_via_api(cfg)
    if secrets:
        _apply_doppler_secrets(cfg, secrets, "Doppler API")
        return

    secrets = _fetch_doppler_secrets_via_cli(cfg)
    if secrets:
        _apply_doppler_secrets(cfg, secrets, "Doppler CLI")
        return

    die(
        "No Doppler credentials found.\n"
        "  Option 1: doppler login && doppler setup --project personal --config dev\n"
        "  Option 2: DOPPLER_TOKEN=dp.st.xxx (service token from https://dashboard.doppler.com)\n"
        f"  Project: {cfg.doppler_project}  Config: {cfg.doppler_config}"
    )
