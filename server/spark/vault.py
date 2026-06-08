"""Fetch secrets from OpenBao/Vault (env -> API -> CLI) into Config."""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping

from .console import die, ok, section, warn


def _apply_vault_secrets(cfg, secrets: Mapping[str, str], source: str) -> None:
    cfg.cf_api_token = secrets.get("CLOUDFLARE_API_TOKEN", "").strip()
    cfg.cf_account_id = secrets.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    cfg.cf_tunnel_token = (
        secrets.get("CF_TUNNEL_TOKEN", "")
        or secrets.get("CLOUDFLARE_TUNNEL_TOKEN", "")
    ).strip()
    cfg.hf_token = secrets.get("HF_TOKEN", "")

    ok(f"Secrets loaded from {source} ({cfg.vault_project}/{cfg.vault_config})")
    if not cfg.cf_api_token:
        die(
            f"Missing CLOUDFLARE_API_TOKEN in secret store "
            f"({cfg.vault_project}/{cfg.vault_config}).\n"
            "  Token needs Account → Cloudflare Tunnel → Edit."
        )
    if not cfg.cf_account_id:
        die(
            f"Missing CLOUDFLARE_ACCOUNT_ID in secret store "
            f"({cfg.vault_project}/{cfg.vault_config})."
        )
    ok("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID loaded")
    if cfg.cf_tunnel_token:
        warn("Using CF_TUNNEL_TOKEN override instead of fetching connector token via API")
    if not cfg.hf_token:
        warn("HF_TOKEN not in secret store — fine for public models")


def _vault_secret_path(cfg) -> str:
    return f"{cfg.vault_project}/{cfg.vault_config}"


def _fetch_vault_secrets_via_api(cfg) -> dict:
    token = cfg.vault_token or os.environ.get("VAULT_TOKEN", "")
    if not token:
        return {}

    url = (
        f"{cfg.vault_addr.rstrip('/')}/v1/{cfg.vault_mount}/data/"
        f"{_vault_secret_path(cfg)}"
    )
    req = urllib.request.Request(url)
    req.add_header("X-Vault-Token", token)
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        die(f"Vault API error {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        die(f"Could not reach Vault at {cfg.vault_addr}: {e.reason}")

    data = payload.get("data", {}).get("data", {})
    if not isinstance(data, dict):
        die("Vault API returned unexpected secret payload shape")
    return data


def _fetch_vault_secrets_via_cli(cfg) -> dict:
    if not shutil.which("vault"):
        return {}

    result = subprocess.run(
        [
            "vault",
            "kv",
            "get",
            "-format=json",
            f"-mount={cfg.vault_mount}",
            _vault_secret_path(cfg),
        ],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "VAULT_ADDR": cfg.vault_addr,
        },
    )
    if result.returncode != 0:
        die(
            "Could not fetch secrets via vault CLI.\n"
            f"  Path: {cfg.vault_mount}/{_vault_secret_path(cfg)}\n"
            "  Run: vault login && vault setup --project personal --config dev\n"
            f"  stderr: {result.stderr.strip()}"
        )

    payload = json.loads(result.stdout)
    data = payload.get("data", {}).get("data", {})
    if not isinstance(data, dict):
        die("Vault CLI returned unexpected secret payload shape")
    return data


def fetch_vault_secrets(cfg):
    section("Fetching secrets from secret store")

    if os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        _apply_vault_secrets(cfg, os.environ, "environment")
        return

    secrets = _fetch_vault_secrets_via_api(cfg)
    if secrets:
        _apply_vault_secrets(cfg, secrets, "Vault API")
        return

    secrets = _fetch_vault_secrets_via_cli(cfg)
    if secrets:
        _apply_vault_secrets(cfg, secrets, "Vault CLI")
        return

    die(
        "No Vault credentials found.\n"
        "  Option 1: vault login && vault setup --project personal --config dev\n"
        "  Option 2: VAULT_TOKEN=hvs.xxx (read-only token from secret-store repo)\n"
        f"  Path: {cfg.vault_mount}/{_vault_secret_path(cfg)}"
    )
