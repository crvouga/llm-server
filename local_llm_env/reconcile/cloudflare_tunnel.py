from __future__ import annotations

import base64
import json
import re
import secrets as pysecrets
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..doppler import doppler_prefix
from ..types import Action, ReconcileResult

_TUNNEL_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def plan_cloudflare(spec: dict[str, Any], secrets: dict[str, str], rotate_tunnel: bool = False) -> ReconcileResult:
    component = "cloudflare"
    result = ReconcileResult(component=component)
    cf = spec["exposure"]["cloudflare"]
    if not cf.get("enabled", True):
        return result

    tunnel_name = cf["tunnel_name"]
    project = spec["secrets"]["project"]
    config = spec["secrets"]["config"]
    prefix = doppler_prefix(project, config)
    account_id = secrets.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = secrets.get("CLOUDFLARE_API_TOKEN", "").strip()

    tunnel_id, credentials_json, removed_tunnels = resolve_tunnel(
        cf=cf,
        secrets=secrets,
        account_id=account_id,
        api_token=api_token,
        rotate_tunnel=rotate_tunnel,
        observed=result.observed,
    )

    if not tunnel_id:
        result.actions.append(
            Action(
                id="create-cloudflared-tunnel",
                component=component,
                description=f"Create cloudflared tunnel `{tunnel_name}` via CLI",
                operation="run_command",
                payload={
                    "command": (
                        f"{prefix}cloudflared tunnel create {tunnel_name} "
                        "2>/dev/null || true"
                    )
                },
            )
        )
        tunnel_id = find_tunnel_id_via_cli(tunnel_name) or ""
        if tunnel_id:
            result.observed["tunnel_source"] = "cloudflared_cli_create"
        else:
            result.observed["pending_tunnel_creation"] = True

    tunnel_ref = tunnel_route_ref(tunnel_id, tunnel_name)
    credentials_path = credentials_path_for_tunnel(tunnel_id)
    if credentials_json and tunnel_id:
        current_credentials = credentials_path.read_text() if credentials_path.exists() else None
        if current_credentials != credentials_json:
            result.actions.append(
                Action(
                    id="write-cloudflared-credentials",
                    component=component,
                    description=f"Write cloudflared credentials `{credentials_path}`",
                    operation="write_file",
                    payload={"path": str(credentials_path), "content": credentials_json},
                )
            )
        result.managed_resources.append(
            {"type": "cloudflared_credentials", "path": str(credentials_path), "tunnel_id": tunnel_id}
        )
    elif tunnel_id:
        result.managed_resources.append(
            {"type": "cloudflared_credentials", "path": str(credentials_path), "tunnel_id": tunnel_id}
        )

    config_path = Path(cf.get("config_path", f"~/.cloudflared/{tunnel_name}.yml")).expanduser()
    ingress = cf.get("routes", [])
    rendered = render_tunnel_config(tunnel_name, tunnel_id, ingress)
    current = config_path.read_text() if config_path.exists() else None
    if current != rendered:
        result.actions.append(
            Action(
                id="write-cloudflared-config",
                component=component,
                description=f"Write cloudflared config `{config_path}`",
                operation="write_file",
                payload={"path": str(config_path), "content": rendered},
            )
        )
    result.managed_resources.append({"type": "cloudflared_config", "path": str(config_path)})

    for route in ingress:
        hostname = route["hostname"]
        result.actions.append(
            Action(
                id=f"dns-route-{hostname}",
                component=component,
                description=f"Ensure DNS route for `{hostname}` via tunnel",
                operation="run_command",
                payload={
                    "command": (
                        f"{prefix}cloudflared tunnel route dns "
                        f"{tunnel_ref} {hostname} 2>/dev/null || true"
                    )
                },
            )
        )
        result.managed_resources.append(
            {"type": "cloudflare_dns_route", "hostname": hostname, "tunnel": tunnel_ref}
        )

    unit_name = cf.get("service_name", "local-llm-cloudflared.service")
    unit_path = Path(spec["services"].get("systemd_user_dir", "~/.config/systemd/user")).expanduser() / unit_name
    unit_content = render_tunnel_unit(unit_name, config_path, spec["services"].get("restart", "always"))
    current_unit = unit_path.read_text() if unit_path.exists() else None
    if current_unit != unit_content:
        result.actions.append(
            Action(
                id="write-cloudflared-unit",
                component=component,
                description=f"Write cloudflared unit `{unit_name}`",
                operation="write_file",
                payload={"path": str(unit_path), "content": unit_content},
            )
        )

    result.actions.append(
        Action(
            id="start-cloudflared-unit",
            component=component,
            description=f"Enable and start `{unit_name}`",
            operation="run_command",
            payload={"command": f"systemctl --user daemon-reload && systemctl --user enable --now {unit_name}"},
        )
    )
    result.managed_resources.append({"type": "systemd_unit", "name": unit_name, "path": str(unit_path)})
    result.managed_resources.append(
        {"type": "cloudflare_tunnel", "name": tunnel_name, "id": tunnel_id or tunnel_name}
    )
    result.observed["tunnel_id"] = tunnel_id or tunnel_name
    result.observed["tunnel_route_ref"] = tunnel_ref
    if removed_tunnels:
        result.observed["removed_tunnel_ids"] = removed_tunnels
    return result


def resolve_tunnel(
    cf: dict[str, Any],
    secrets: dict[str, str],
    account_id: str,
    api_token: str,
    rotate_tunnel: bool,
    observed: dict[str, Any],
) -> tuple[str, str, list[str]]:
    tunnel_name = cf["tunnel_name"]
    removed_tunnels: list[str] = []
    existing: list[dict[str, str]] = []
    api_error: str | None = None

    if account_id and api_token:
        try:
            existing = list_tunnels(account_id, api_token, tunnel_name)
        except RuntimeError as error:
            api_error = str(error)
            observed["cloudflare_api_unavailable"] = api_error
    elif rotate_tunnel:
        raise RuntimeError(
            "Missing `CLOUDFLARE_ACCOUNT_ID` or `CLOUDFLARE_API_TOKEN` in Doppler secrets"
        )

    if rotate_tunnel:
        if api_error:
            raise RuntimeError(
                "Cloudflare tunnel rotation requires a valid API token with tunnel read/edit "
                f"scopes. Original error: {api_error}"
            ) from None
        for tunnel in existing:
            delete_tunnel(account_id, api_token, tunnel["id"])
            removed_tunnels.append(tunnel["id"])
        tunnel_id, credentials_json = create_tunnel(account_id, api_token, tunnel_name)
        observed["tunnel_rotated"] = True
        observed["tunnel_source"] = "cloudflare_api"
        return tunnel_id, credentials_json, removed_tunnels

    observed["tunnel_rotated"] = False

    if existing:
        observed["tunnel_source"] = "cloudflare_api"
        return existing[0]["id"], "", removed_tunnels

    tunnel_id = secret_tunnel_id(cf, secrets)
    credentials_json = secret_tunnel_credentials(cf, secrets)
    if tunnel_id:
        observed["tunnel_source"] = "doppler"
        return tunnel_id, credentials_json, removed_tunnels

    config_path = Path(cf.get("config_path", f"~/.cloudflared/{tunnel_name}.yml")).expanduser()
    if config_path.exists():
        tunnel_id = parse_tunnel_id_from_config(config_path.read_text())
        if tunnel_id:
            observed["tunnel_source"] = "config_file"
            return tunnel_id, "", removed_tunnels

    tunnel_id = find_tunnel_id_from_credentials_dir()
    if tunnel_id:
        observed["tunnel_source"] = "credentials_dir"
        return tunnel_id, "", removed_tunnels

    tunnel_id = find_tunnel_id_via_cli(tunnel_name)
    if tunnel_id:
        observed["tunnel_source"] = "cloudflared_cli"
        return tunnel_id, "", removed_tunnels

    return "", "", removed_tunnels


def secret_tunnel_id(cf: dict[str, Any], secrets: dict[str, str]) -> str:
    key = cf.get("tunnel_id_secret_key", "CLOUDFLARE_TUNNEL_ID")
    return secrets.get(key, "").strip()


def secret_tunnel_credentials(cf: dict[str, Any], secrets: dict[str, str]) -> str:
    key = cf.get("credentials_file_secret_key", "CF_TUNNEL_CREDENTIALS_JSON")
    raw = secrets.get(key, "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict):
        return json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    return raw


def parse_tunnel_id_from_config(config_text: str) -> str:
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("tunnel:"):
            value = stripped.split(":", 1)[1].strip()
            if _TUNNEL_ID_RE.match(value):
                return value
    return ""


def find_tunnel_id_from_credentials_dir() -> str:
    creds_dir = Path("~/.cloudflared").expanduser()
    if not creds_dir.is_dir():
        return ""
    for cred_file in sorted(creds_dir.glob("*.json")):
        try:
            payload = json.loads(cred_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        tunnel_id = payload.get("TunnelID", "")
        if isinstance(tunnel_id, str) and _TUNNEL_ID_RE.match(tunnel_id):
            return tunnel_id
    return ""


def find_tunnel_id_via_cli(tunnel_name: str) -> str:
    result = subprocess.run(
        ["cloudflared", "tunnel", "list", "--output", "json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    try:
        tunnels = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    if not isinstance(tunnels, list):
        return ""
    for tunnel in tunnels:
        if tunnel.get("name") == tunnel_name:
            tunnel_id = tunnel.get("id", "")
            if isinstance(tunnel_id, str) and _TUNNEL_ID_RE.match(tunnel_id):
                return tunnel_id
    return ""


def credentials_path_for_tunnel(tunnel_id: str) -> Path:
    return Path(f"~/.cloudflared/{tunnel_id}.json").expanduser()


def tunnel_route_ref(tunnel_id: str, tunnel_name: str) -> str:
    if tunnel_id and _TUNNEL_ID_RE.match(tunnel_id):
        return tunnel_id
    return tunnel_name


def plan_cloudflare_destroy(spec: dict[str, Any], state: dict[str, Any]) -> ReconcileResult:
    component = "cloudflare"
    result = ReconcileResult(component=component)
    cf = spec["exposure"]["cloudflare"]
    project = spec["secrets"]["project"]
    config = spec["secrets"]["config"]
    prefix = doppler_prefix(project, config)

    unit_name = cf.get("service_name", "local-llm-cloudflared.service")
    result.actions.append(
        Action(
            id="stop-cloudflared-unit",
            component=component,
            description=f"Stop and disable `{unit_name}`",
            operation="run_command",
            payload={"command": f"systemctl --user disable --now {unit_name} || true"},
            destructive=True,
        )
    )

    for resource in state.get("managed_resources", []):
        if resource.get("type") == "cloudflare_dns_route":
            hostname = resource["hostname"]
            tunnel = resource["tunnel"]
            result.actions.append(
                Action(
                    id=f"delete-dns-route-{hostname}",
                    component=component,
                    description=f"Remove Cloudflare DNS tunnel route for `{hostname}`",
                    operation="run_command",
                    payload={"command": f"{prefix}cloudflared tunnel route dns --delete {tunnel} {hostname} || true"},
                    destructive=True,
                )
            )
        if resource.get("type") in {"cloudflared_config", "cloudflared_credentials"}:
            result.actions.append(
                Action(
                    id=f"delete-cloudflared-config-{Path(resource['path']).name}",
                    component=component,
                    description=f"Delete cloudflared file `{resource['path']}`",
                    operation="delete_file",
                    payload={"path": resource["path"]},
                    destructive=True,
                )
            )
        if resource.get("type") == "cloudflare_tunnel":
            tunnel_id = resource.get("id")
            if tunnel_id:
                result.actions.append(
                    Action(
                        id=f"delete-tunnel-{tunnel_id}",
                        component=component,
                        description=f"Delete Cloudflare tunnel `{tunnel_id}`",
                        operation="run_command",
                        payload={
                            "command": (
                                f"{prefix}curl -fsS -X DELETE "
                                "-H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' "
                                "-H 'Content-Type: application/json' "
                                f"'https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/cfd_tunnel/{tunnel_id}' || true"
                            )
                        },
                        destructive=True,
                    )
                )
    return result


def render_tunnel_config(tunnel_name: str, tunnel_id: str, ingress: list[dict[str, str]]) -> str:
    tunnel_ref = tunnel_route_ref(tunnel_id, tunnel_name)
    lines = [f"tunnel: {tunnel_ref}"]
    if tunnel_id and _TUNNEL_ID_RE.match(tunnel_id):
        lines.append(f"credentials-file: ~/.cloudflared/{tunnel_id}.json")
    lines.append("ingress:")
    for route in ingress:
        lines.append(f"  - hostname: {route['hostname']}")
        lines.append(f"    service: {route['service']}")
    lines.append("  - service: http_status:404")
    lines.append("")
    lines.append(f"# managed tunnel name: {tunnel_name}")
    return "\n".join(lines) + "\n"


def resolve_cloudflared_bin() -> str:
    candidates = [
        shutil.which("cloudflared"),
        str(Path("~/.local/bin/cloudflared").expanduser()),
        "/usr/local/bin/cloudflared",
        "/usr/bin/cloudflared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return "cloudflared"


def render_tunnel_unit(unit_name: str, config_path: Path, restart_policy: str) -> str:
    cloudflared_bin = resolve_cloudflared_bin()
    return f"""[Unit]
Description=Cloudflare tunnel for local LLM services ({unit_name})
After=network.target

[Service]
Type=simple
ExecStart={cloudflared_bin} tunnel --config {config_path} run
Restart={restart_policy}
RestartSec=5

[Install]
WantedBy=default.target
"""


def _cf_request(
    account_id: str,
    api_token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Cloudflare API {method} {path} failed: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cloudflare API {method} {path} failed: {error}") from error

    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare API {method} {path} failed: {payload.get('errors')}")
    return payload


def list_tunnels(account_id: str, api_token: str, tunnel_name: str) -> list[dict[str, str]]:
    payload = _cf_request(account_id, api_token, "GET", "/cfd_tunnel?is_deleted=false")
    tunnels: list[dict[str, str]] = []
    for item in payload.get("result", []):
        tunnel_id = item.get("id")
        if item.get("name") == tunnel_name and tunnel_id:
            tunnels.append({"id": tunnel_id, "name": tunnel_name})
    return tunnels


def delete_tunnel(account_id: str, api_token: str, tunnel_id: str) -> None:
    encoded_id = urllib.parse.quote(tunnel_id)
    _cf_request(account_id, api_token, "DELETE", f"/cfd_tunnel/{encoded_id}")


def create_tunnel(account_id: str, api_token: str, tunnel_name: str) -> tuple[str, str]:
    tunnel_secret = base64.b64encode(pysecrets.token_bytes(32)).decode("ascii")
    payload = _cf_request(
        account_id,
        api_token,
        "POST",
        "/cfd_tunnel",
        body={"name": tunnel_name, "tunnel_secret": tunnel_secret},
    )
    tunnel_id = payload.get("result", {}).get("id", "")
    if not tunnel_id:
        raise RuntimeError("Cloudflare API did not return tunnel id")
    credentials = {
        "AccountTag": account_id,
        "TunnelSecret": tunnel_secret,
        "TunnelID": tunnel_id,
    }
    return tunnel_id, json.dumps(credentials, indent=2, sort_keys=True) + "\n"

