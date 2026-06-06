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
    path = Path(config.get("binary_path", "~/.local/bin/lmstudio")).expanduser()
    if install_method == "appimage":
        url = config.get(
            "appimage_url",
            "https://installers.lmstudio.ai/linux/x64/latest/LM-Studio.AppImage",
        )
        return (
            f"mkdir -p \"{path.parent}\" && "
            f"curl -L \"{url}\" -o /tmp/lmstudio.AppImage && "
            "chmod +x /tmp/lmstudio.AppImage && "
            f"mv /tmp/lmstudio.AppImage \"{path}\""
        )
    return "echo 'Unsupported LM Studio install method' && exit 1"


