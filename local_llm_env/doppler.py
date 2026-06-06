from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class DopplerError(RuntimeError):
    pass


def doppler_installed() -> bool:
    return shutil.which("doppler") is not None


def ensure_doppler_access(project: str, config: str) -> None:
    command = [
        "doppler",
        "configs",
        "get",
        config,
        "--project",
        project,
        "--json",
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise DopplerError(
            "Unable to access Doppler config. Run `doppler login` and check project/config.\n"
            f"stderr:\n{result.stderr}"
        )


def fetch_secrets(project: str, config: str) -> dict[str, str]:
    command = [
        "doppler",
        "secrets",
        "download",
        "--project",
        project,
        "--config",
        config,
        "--no-file",
        "--format",
        "json",
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise DopplerError(f"Failed to fetch Doppler secrets:\n{result.stderr}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise DopplerError("Doppler secrets response is not a JSON object")
    cleaned: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            cleaned[key] = value
        else:
            cleaned[key] = json.dumps(value)
    return cleaned


def validate_required_keys(secrets: dict[str, str], required_keys: list[str]) -> list[str]:
    return [item for item in required_keys if item not in secrets or not secrets[item]]


def doppler_prefix(project: str, config: str) -> str:
    return (
        "doppler run "
        f"--project {project} "
        f"--config {config} -- "
    )

