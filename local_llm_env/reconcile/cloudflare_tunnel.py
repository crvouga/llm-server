from __future__ import annotations

import base64
import json
import secrets as pysecrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..doppler import doppler_prefix
from ..types import Action, ReconcileResult


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
    if not account_id or not api_token:
        raise RuntimeError("Missing `CLOUDFLARE_ACCOUNT_ID` or `CLOUDFLARE_API_TOKEN` in Doppler secrets")

    try:
        existing = list_tunnels(account_id, api_token, tunnel_name)
    except RuntimeError as error:
        if rotate_tunnel:
            raise RuntimeError(
                "Cloudflare tunnel lifecycle management requires API token scopes for tunnels "
                f"(read/edit). Original error: {error}"
            ) from error
        existing = []
        result.observed["cloudflare_api_unavailable"] = str(error)
    removed_tunnels: list[str] = []
    if rotate_tunnel:
        for tunnel in existing:
            delete_tunnel(account_id, api_token, tunnel["id"])
            removed_tunnels.append(tunnel["id"])
        tunnel_id, credentials_json = create_tunnel(account_id, api_token, tunnel_name)
        result.observed["tunnel_rotated"] = True
    else:
        tunnel_id = existing[0]["id"] if existing else ""
        credentials_json = ""
        result.observed["tunnel_rotated"] = False

    if not tunnel_id:
        if rotate_tunnel:
            raise RuntimeError(
                f"Failed to create Cloudflare tunnel `{tunnel_name}` during apply planning."
            )
        tunnel_id = "<created-on-apply>"
        result.observed["pending_tunnel_creation"] = True

    credentials_path = Path(f"~/.cloudflared/{tunnel_id}.json").expanduser()
    current_credentials = credentials_path.read_text() if credentials_path.exists() else None
    if credentials_json and current_credentials != credentials_json:
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
                        f"{tunnel_id} {hostname}"
                    )
                },
            )
        )
        result.managed_resources.append(
            {"type": "cloudflare_dns_route", "hostname": hostname, "tunnel": tunnel_id}
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
    result.managed_resources.append({"type": "cloudflare_tunnel", "name": tunnel_name, "id": tunnel_id})
    result.observed["tunnel_id"] = tunnel_id
    if removed_tunnels:
        result.observed["removed_tunnel_ids"] = removed_tunnels
    return result


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
    lines = [
        f"tunnel: {tunnel_id}",
        f"credentials-file: ~/.cloudflared/{tunnel_id}.json",
        "ingress:",
    ]
    for route in ingress:
        lines.append(f"  - hostname: {route['hostname']}")
        lines.append(f"    service: {route['service']}")
    lines.append("  - service: http_status:404")
    lines.append("")
    lines.append(f"# managed tunnel name: {tunnel_name}")
    return "\n".join(lines) + "\n"


def render_tunnel_unit(unit_name: str, config_path: Path, restart_policy: str) -> str:
    return f"""[Unit]
Description=Cloudflare tunnel for local LLM services ({unit_name})
After=network.target

[Service]
Type=simple
ExecStart=cloudflared tunnel --config {config_path} run
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

