"""Cloudflare tunnel: API config (DNS + ingress), token resolution, and the
local cloudflared connector process.
"""

import os
import shutil
import subprocess
import time

from .console import die, info, ok, section, warn
from .runtime import _stop_spark_tunnel, register
from .webapi import CloudflareAPIError, http_get, http_post, http_put


def cf_headers(cfg):
    return {
        "Authorization": f"Bearer {cfg.cf_api_token}",
        "Content-Type": "application/json",
    }


def _cf_tunnel_api_base(cfg) -> str:
    return (
        f"https://api.cloudflare.com/client/v4/accounts/{cfg.cf_account_id}/cfd_tunnel"
    )


def _cf_api_token_help(cfg) -> str:
    return (
        f"Grant CLOUDFLARE_API_TOKEN Account → Cloudflare Tunnel → Edit "
        f"({cfg.doppler_project}/{cfg.doppler_config})."
    )


def precheck_cf_tunnel(cfg):
    section("Precheck: Cloudflare tunnel")
    if not shutil.which("cloudflared"):
        die("cloudflared not found — install it or run: make ensure-system-deps")

    if cfg.cf_tunnel_token and len(cfg.cf_tunnel_token) < 40:
        die(
            "CF_TUNNEL_TOKEN looks too short — copy the full Docker connector token "
            "from the Cloudflare Zero Trust dashboard."
        )

    if not cfg.cf_api_token or not cfg.cf_account_id:
        die(
            "Cloudflare API credentials missing from Doppler.\n"
            + _cf_api_token_help(cfg)
        )

    info(f"Checking API access for tunnel '{cfg.cf_tunnel_name}'...")
    try:
        resp = http_get(
            f"{_cf_tunnel_api_base(cfg)}?name={cfg.cf_tunnel_name}&is_deleted=false",
            cf_headers(cfg),
        )
    except CloudflareAPIError as e:
        die(
            "Cloudflare tunnel precheck failed — refusing to start vLLM.\n\n"
            f"  API error: HTTP {e.code}: {e.message}\n\n"
            "  Your CLOUDFLARE_API_TOKEN is valid but lacks tunnel permissions.\n"
            f"  Fix: {_cf_api_token_help(cfg)}"
        )

    if not resp.get("success", True):
        die(f"Cloudflare API returned success=false: {resp}")
    ok("Cloudflare API can list tunnels")


def _cf_public_url(cfg) -> str:
    return f"https://{cfg.cf_tunnel_hostname}"


def _cf_service_url(cfg) -> str:
    return f"http://127.0.0.1:{cfg.vllm_port}"


def merge_tunnel_ingress(
    existing: list[dict], hostname: str, service: str
) -> list[dict]:
    """Merge a public hostname route into tunnel ingress (catch-all last)."""
    merged: list[dict] = []
    replaced = False
    for rule in existing:
        svc = rule.get("service", "")
        if rule.get("hostname") == hostname:
            merged.append(
                {"hostname": hostname, "service": service, "originRequest": {}}
            )
            replaced = True
        elif "http_status" in str(svc):
            continue
        else:
            merged.append(rule)
    if not replaced:
        merged.append(
            {"hostname": hostname, "service": service, "originRequest": {}}
        )
    merged.append({"service": "http_status:404"})
    return merged


def _cf_zone_id_for_hostname(cfg, hostname: str, hdrs: dict) -> str:
    zone_name = hostname.split(".", 1)[1]
    resp = http_get(
        f"https://api.cloudflare.com/client/v4/zones?name={zone_name}", hdrs
    )
    zones = resp.get("result", [])
    if not zones:
        die(f"Cloudflare zone not found for hostname '{hostname}' (zone: {zone_name})")
    return zones[0]["id"]


def _cf_ensure_tunnel_dns(cfg, tunnel_id: str, hdrs: dict) -> None:
    hostname = cfg.cf_tunnel_hostname
    zone_id = _cf_zone_id_for_hostname(cfg, hostname, hdrs)
    record_name = hostname.split(".", 1)[0]
    content = f"{tunnel_id}.cfargotunnel.com"

    resp = http_get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        f"?type=CNAME&name={hostname}",
        hdrs,
    )
    records = resp.get("result", [])
    if records:
        rec = records[0]
        if rec.get("content") == content and rec.get("proxied"):
            ok(f"DNS already routed: {hostname} → {content}")
            return
        http_put(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{rec['id']}",
            {
                "type": "CNAME",
                "name": record_name,
                "content": content,
                "proxied": True,
            },
            hdrs,
        )
    else:
        http_post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            {
                "type": "CNAME",
                "name": record_name,
                "content": content,
                "proxied": True,
            },
            hdrs,
        )
    ok(f"DNS routed: {hostname} → {content}")


def _ingress_already_routed(
    existing: list[dict], hostname: str, service: str
) -> bool:
    for rule in existing:
        if rule.get("hostname") == hostname and rule.get("service") == service:
            return True
    return False


def _tunnel_ingress_from_config_response(resp: dict) -> list[dict]:
    """Parse ingress rules from GET /cfd_tunnel/{id}/configurations."""
    result = resp.get("result") or {}
    config = result.get("config") or {}
    return config.get("ingress", []) or []


def _cf_ensure_tunnel_ingress(cfg, tunnel_id: str, hdrs: dict) -> None:
    base = _cf_tunnel_api_base(cfg)
    service = _cf_service_url(cfg)
    hostname = cfg.cf_tunnel_hostname

    existing: list[dict] = []
    try:
        resp = http_get(f"{base}/{tunnel_id}/configurations", hdrs)
        existing = _tunnel_ingress_from_config_response(resp)
    except CloudflareAPIError as e:
        if e.code != 404:
            raise

    if _ingress_already_routed(existing, hostname, service):
        ok(f"Tunnel ingress already set: {hostname} → {service}")
        return

    ingress = merge_tunnel_ingress(existing, hostname, service)
    http_put(
        f"{base}/{tunnel_id}/configurations",
        {"config": {"ingress": ingress}},
        hdrs,
    )
    ok(f"Tunnel ingress: {hostname} → {service}")


def _cf_get_or_create_tunnel_id(cfg, hdrs: dict) -> str:
    base = _cf_tunnel_api_base(cfg)
    resp = http_get(f"{base}?name={cfg.cf_tunnel_name}&is_deleted=false", hdrs)
    tunnels = resp.get("result", [])
    if tunnels:
        tunnel_id = tunnels[0]["id"]
        ok(f"Reusing tunnel '{cfg.cf_tunnel_name}' ({tunnel_id})")
        return tunnel_id

    info(f"Creating tunnel '{cfg.cf_tunnel_name}'...")
    resp = http_post(
        base,
        {
            "name": cfg.cf_tunnel_name,
            "tunnel_secret": os.urandom(32).hex(),
            "config_src": "cloudflare",
        },
        hdrs,
    )
    tunnel_id = resp["result"]["id"]
    ok(f"Created tunnel '{cfg.cf_tunnel_name}' ({tunnel_id})")
    return tunnel_id


def resolve_cf_tunnel_token(cfg) -> str:
    """Return connector token; ensure DNS + ingress for cfg.cf_tunnel_hostname."""
    section("Resolving Cloudflare tunnel token (API)")
    base = _cf_tunnel_api_base(cfg)
    hdrs = cf_headers(cfg)

    try:
        tunnel_id = _cf_get_or_create_tunnel_id(cfg, hdrs)
        section(f"Routing tunnel to {_cf_public_url(cfg)}")
        _cf_ensure_tunnel_ingress(cfg, tunnel_id, hdrs)
        _cf_ensure_tunnel_dns(cfg, tunnel_id, hdrs)

        if cfg.cf_tunnel_token:
            ok("Using connector token from secrets (routes updated via API)")
            return cfg.cf_tunnel_token

        tok = http_get(f"{base}/{tunnel_id}/token", hdrs)
        return tok["result"]
    except CloudflareAPIError as e:
        die(
            f"Could not configure Cloudflare tunnel via API: HTTP {e.code}: {e.message}\n"
            + _cf_api_token_help(cfg)
            + "\n  DNS setup also needs Zone → DNS → Edit on the API token."
        )


def start_cf_tunnel(cfg, tunnel_token):
    section("Starting Cloudflare tunnel")
    cf_log = cfg.helper_dir / "cloudflare-tunnel.log"
    cfg.helper_dir.mkdir(parents=True, exist_ok=True)

    _stop_spark_tunnel(cfg)
    time.sleep(1)

    log_file = open(cf_log, "w")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token],
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    (cfg.helper_dir / "cloudflared.pid").write_text(str(proc.pid))
    register(proc)
    info(
        f"Tunnel managed by this process — stops on Ctrl+C / make server-stop "
        f"({cfg.cf_tunnel_hostname})"
    )

    info("Waiting for tunnel to connect...")
    time.sleep(6)

    if proc.poll() is not None:
        die(f"cloudflared exited.\nLog:\n{cf_log.read_text()[-1000:]}")

    ok(f"Cloudflare tunnel running (PID {proc.pid})")

    return _cf_public_url(cfg)
