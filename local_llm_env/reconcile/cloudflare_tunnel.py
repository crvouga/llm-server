from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..doppler import doppler_prefix
from ..types import Action, ReconcileResult


def plan_cloudflare(spec: dict[str, Any], secrets: dict[str, str]) -> ReconcileResult:
    component = "cloudflare"
    result = ReconcileResult(component=component)
    cf = spec["exposure"]["cloudflare"]
    if not cf.get("enabled", True):
        return result

    tunnel_name = cf["tunnel_name"]
    project = spec["secrets"]["project"]
    config = spec["secrets"]["config"]
    prefix = doppler_prefix(project, config)

    known_tunnel_id = get_existing_tunnel_id(prefix, tunnel_name)
    tunnel_id = known_tunnel_id or secrets.get(cf["tunnel_id_secret_key"], "")

    if not tunnel_id:
        result.actions.append(
            Action(
                id="create-cloudflare-tunnel",
                component=component,
                description=f"Create Cloudflare tunnel `{tunnel_name}`",
                operation="run_command",
                payload={"command": f"{prefix}cloudflared tunnel create {tunnel_name}"},
            )
        )
    else:
        result.observed["tunnel_id"] = tunnel_id

    config_path = Path(cf.get("config_path", f"~/.cloudflared/{tunnel_name}.yml")).expanduser()
    ingress = cf.get("routes", [])
    rendered = render_tunnel_config(tunnel_name, tunnel_id or "${CF_TUNNEL_ID}", ingress)
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
                        f"{tunnel_id or tunnel_name} {hostname}"
                    )
                },
            )
        )
        result.managed_resources.append(
            {"type": "cloudflare_dns_route", "hostname": hostname, "tunnel": tunnel_id or tunnel_name}
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
        if resource.get("type") == "cloudflared_config":
            result.actions.append(
                Action(
                    id=f"delete-cloudflared-config-{Path(resource['path']).name}",
                    component=component,
                    description=f"Delete cloudflared config `{resource['path']}`",
                    operation="delete_file",
                    payload={"path": resource["path"]},
                    destructive=True,
                )
            )
    return result


def get_existing_tunnel_id(command_prefix: str, tunnel_name: str) -> str | None:
    command = f"{command_prefix}cloudflared tunnel list --output json"
    process = subprocess.run(command, shell=True, text=True, capture_output=True)
    if process.returncode != 0:
        return None
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    for item in payload:
        if item.get("name") == tunnel_name:
            return item.get("id")
    return None


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

