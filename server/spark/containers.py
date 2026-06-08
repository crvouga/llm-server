"""Generic Docker container helpers for the Atlas engine."""

import subprocess

from .config import _CONFIG_HASH_LABEL
from .console import info
from .shell import run


def _image_exists_locally(docker_cmd, image: str) -> bool:
    return (
        subprocess.run(
            [*docker_cmd, "image", "inspect", image],
            capture_output=True,
        ).returncode
        == 0
    )


def _named_container_status(docker_cmd, name: str) -> str:
    r = subprocess.run(
        [
            *docker_cmd,
            "inspect",
            "--format",
            "{{.State.Status}}",
            name,
        ],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else "missing"


def _container_status(cfg):
    return _named_container_status(cfg.docker_cmd, cfg.container_name)


def _container_restart_count(cfg):
    r = subprocess.run(
        [
            *cfg.docker_cmd,
            "inspect",
            "--format",
            "{{.RestartCount}}",
            cfg.container_name,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return int(r.stdout.strip()) if r.returncode == 0 else 0
    except ValueError:
        return 0


def _container_logs_tail(cfg, lines=30):
    r = subprocess.run(
        [*cfg.docker_cmd, "logs", "--tail", str(lines), cfg.container_name],
        capture_output=True,
        text=True,
    )
    return (r.stdout + r.stderr).strip()


def _latest_container_log_line(cfg) -> str:
    logs = _container_logs_tail(cfg, lines=15)
    for line in reversed(logs.splitlines()):
        line = line.strip()
        if line and not line.startswith("["):
            return line[:120]
    return ""


def _container_config_hash(cfg) -> str:
    r = subprocess.run(
        [
            *cfg.docker_cmd,
            "inspect",
            "--format",
            f"{{{{ index .Config.Labels \"{_CONFIG_HASH_LABEL}\" }}}}",
            cfg.container_name,
        ],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def remove_container(cfg, docker_cmd):
    result = subprocess.run(
        [*docker_cmd, "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if cfg.container_name not in result.stdout.splitlines():
        return
    status = _container_status(cfg)
    if status == "running":
        info(f"Stopping existing container '{cfg.container_name}'...")
        run([*docker_cmd, "stop", cfg.container_name])
    run([*docker_cmd, "rm", cfg.container_name])
