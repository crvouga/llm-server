from __future__ import annotations

from pathlib import Path
from typing import Any

from ..types import Action, ReconcileResult


def plan_services(spec: dict[str, Any], manifest: dict[str, Any]) -> ReconcileResult:
    component = "services"
    result = ReconcileResult(component=component)
    services_cfg = spec["services"]
    if not services_cfg.get("use_systemd_user", True):
        return result

    unit_dir = Path(services_cfg.get("systemd_user_dir", "~/.config/systemd/user")).expanduser()
    result.actions.append(
        Action(
            id="ensure-systemd-user-dir",
            component=component,
            description=f"Ensure systemd user unit dir exists `{unit_dir}`",
            operation="mkdir",
            payload={"path": str(unit_dir)},
        )
    )

    units = render_units(spec, manifest)
    for unit_name, unit_content in units.items():
        path = unit_dir / unit_name
        current = path.read_text() if path.exists() else None
        if current != unit_content:
            result.actions.append(
                Action(
                    id=f"write-unit-{unit_name}",
                    component=component,
                    description=f"Write/update systemd user unit `{unit_name}`",
                    operation="write_file",
                    payload={"path": str(path), "content": unit_content},
                )
            )
        result.actions.append(
            Action(
                id=f"enable-start-{unit_name}",
                component=component,
                description=f"Enable and start `{unit_name}`",
                operation="run_command",
                payload={"command": f"systemctl --user daemon-reload && systemctl --user enable --now {unit_name}"},
            )
        )
        result.managed_resources.append({"type": "systemd_unit", "name": unit_name, "path": str(path)})

    return result


def plan_services_destroy(state: dict[str, Any]) -> ReconcileResult:
    component = "services"
    result = ReconcileResult(component=component)
    for resource in state.get("managed_resources", []):
        if resource.get("type") != "systemd_unit":
            continue
        name = resource["name"]
        path = resource["path"]
        result.actions.append(
            Action(
                id=f"disable-stop-{name}",
                component=component,
                description=f"Stop and disable `{name}`",
                operation="run_command",
                payload={"command": f"systemctl --user disable --now {name} || true"},
                destructive=True,
            )
        )
        result.actions.append(
            Action(
                id=f"delete-unit-{name}",
                component=component,
                description=f"Delete unit file `{path}`",
                operation="delete_file",
                payload={"path": path},
                destructive=True,
            )
        )
    return result


def render_units(spec: dict[str, Any], manifest: dict[str, Any]) -> dict[str, str]:
    servers = spec["servers"]
    host = spec["host"]
    services = spec["services"]
    model_by_backend: dict[str, str] = {}
    for model in manifest["models"]:
        model_by_backend.setdefault(model["backend"], model["id"])

    restart_policy = services.get("restart", "always")
    health_timeout = int(services.get("healthcheck_timeout_seconds", 30))
    units: dict[str, str] = {}

    lmstudio_server = servers.get("lmstudio", {})
    if lmstudio_server.get("enabled", True):
        lmstudio_bin = host.get("lmstudio", {}).get("binary_path", "~/.local/bin/lmstudio")
        model_id = lmstudio_server.get("model_id", model_by_backend.get("lmstudio", ""))
        units["local-llm-lmstudio.service"] = f"""[Unit]
Description=Local LLM LM Studio server
After=network.target

[Service]
Type=simple
ExecStart={lmstudio_bin} --headless --model {model_id} --host {lmstudio_server.get("host", "127.0.0.1")} --port {lmstudio_server.get("port", 1234)}
Restart={restart_policy}
RestartSec=3
TimeoutStartSec={health_timeout}

[Install]
WantedBy=default.target
"""

    llama_server = servers.get("llamacpp", {})
    if llama_server.get("enabled", True):
        llama_bin = host.get("llamacpp", {}).get("binary_path", "~/.local/bin/llama-server")
        model_path = llama_server.get("model_path")
        if not model_path:
            default_id = model_by_backend.get("llamacpp", "model")
            model_path = f"{spec['models'].get('download_dir', '~/.local/share/local-llm-models')}/{default_id}.gguf"
        extra_args = " ".join(llama_server.get("extra_args", []))
        units["local-llm-llamacpp.service"] = f"""[Unit]
Description=Local LLM llama.cpp server
After=network.target

[Service]
Type=simple
ExecStart={llama_bin} --model {model_path} --host {llama_server.get("host", "127.0.0.1")} --port {llama_server.get("port", 8080)} {extra_args}
Restart={restart_policy}
RestartSec=3
TimeoutStartSec={health_timeout}

[Install]
WantedBy=default.target
"""

    return units

