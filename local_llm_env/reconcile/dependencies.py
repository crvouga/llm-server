from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..types import Action, ReconcileResult


def plan_dependencies(spec: dict[str, Any]) -> ReconcileResult:
    host = spec["host"]
    component = "dependencies"
    result = ReconcileResult(component=component)

    for binary in host.get("required_binaries", []):
        exists = shutil.which(binary) is not None
        result.observed[f"binary:{binary}"] = "present" if exists else "missing"
        if not exists:
            command = install_command_for_binary(binary, host)
            result.actions.append(
                Action(
                    id=f"install-binary-{binary}",
                    component=component,
                    description=f"Install missing binary `{binary}`",
                    operation="run_command",
                    payload={"command": command},
                )
            )

    lmstudio_cfg = host.get("lmstudio", {})
    lmstudio_path = Path(lmstudio_cfg.get("binary_path", "~/.local/bin/lmstudio")).expanduser()
    if not lmstudio_path.exists():
        result.actions.append(
            Action(
                id="install-lmstudio",
                component=component,
                description="Install LM Studio binary",
                operation="run_command",
                payload={"command": install_lmstudio_command(lmstudio_cfg)},
            )
        )
    result.observed["lmstudio_binary"] = str(lmstudio_path)
    result.managed_resources.append({"type": "binary", "name": "lmstudio", "path": str(lmstudio_path)})

    llamacpp_cfg = host.get("llamacpp", {})
    llama_path = Path(llamacpp_cfg.get("binary_path", "~/.local/bin/llama-server")).expanduser()
    if not llama_path.exists():
        result.actions.append(
            Action(
                id="install-llama-server",
                component=component,
                description="Install llama.cpp server binary",
                operation="run_command",
                payload={"command": install_llamacpp_command(llamacpp_cfg)},
            )
        )
    result.observed["llama_server_binary"] = str(llama_path)
    result.managed_resources.append(
        {"type": "binary", "name": "llama-server", "path": str(llama_path)}
    )
    return result


def install_command_for_binary(binary: str, host_spec: dict[str, Any]) -> str:
    manager = host_spec.get("package_manager", "apt")
    if manager == "apt":
        return f"sudo apt-get update && sudo apt-get install -y {binary}"
    if manager == "brew":
        return f"brew install {binary}"
    return (
        f"echo 'Install {binary} manually or set host.package_manager. "
        "No known installer for current package manager.' && exit 1"
    )


def install_lmstudio_command(config: dict[str, Any]) -> str:
    install_method = config.get("install_method", "appimage")
    path = config.get("binary_path", "~/.local/bin/lmstudio")
    if install_method == "appimage":
        url = config.get(
            "appimage_url",
            "https://installers.lmstudio.ai/linux/x64/latest/LM-Studio.AppImage",
        )
        return (
            "mkdir -p ~/.local/bin && "
            f"curl -L \"{url}\" -o /tmp/lmstudio.AppImage && "
            "chmod +x /tmp/lmstudio.AppImage && "
            f"mv /tmp/lmstudio.AppImage \"{path}\""
        )
    return "echo 'Unsupported LM Studio install method' && exit 1"


def install_llamacpp_command(config: dict[str, Any]) -> str:
    install_method = config.get("install_method", "github_release")
    path = config.get("binary_path", "~/.local/bin/llama-server")
    if install_method == "github_release":
        url = config.get(
            "binary_url",
            "https://github.com/ggerganov/llama.cpp/releases/latest/download/llama-server",
        )
        return (
            "mkdir -p ~/.local/bin && "
            f"curl -L \"{url}\" -o \"{path}\" && "
            f"chmod +x \"{path}\""
        )
    return "echo 'Unsupported llama.cpp install method' && exit 1"

