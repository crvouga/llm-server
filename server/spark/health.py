"""Readiness probes + the boot wait loop, engine-aware."""

import json
import os
import urllib.request

from .config import _boot_time_hint
from .console import die, info, ok, section
from .constants import _SERVED_MODEL
from .containers import (
    _container_logs_tail,
    _container_restart_count,
    _container_status,
    _latest_container_log_line,
)
from .runtime import _exit_on_shutdown, _sleep


def _health_ok(cfg) -> bool:
    url = f"http://localhost:{cfg.vllm_port}/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _vllm_ready(cfg) -> bool:
    if not _health_ok(cfg):
        return False
    url = f"http://localhost:{cfg.vllm_port}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
            return any(
                m.get("id") == _SERVED_MODEL for m in data.get("data", [])
            )
    except Exception:
        return False


def _atlas_ready(cfg) -> bool:
    """Atlas serves the OpenAI API on its port; readiness = /v1/models with models."""
    url = f"http://localhost:{cfg.service_port}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read())
            return bool(data.get("data"))
    except Exception:
        return False


def _server_ready(cfg) -> bool:
    return _atlas_ready(cfg) if cfg.engine == "atlas" else _vllm_ready(cfg)


def _health_max_wait(cfg) -> int:
    if cfg.engine == "atlas":
        # Atlas cold-starts in <2 min once cached, but the first run downloads the
        # ~35 GB FP8 checkpoint into the HF cache — allow generous headroom.
        return int(os.environ.get("ATLAS_READY_TIMEOUT", "3600"))
    return {0: 180, 1: 480, 2: 720}.get(cfg.optimization_level, 480)


def _health_poll_interval(elapsed: int) -> int:
    return 2 if elapsed < 60 else 5


def _gpu_oom_hint(logs: str) -> str:
    lower = logs.lower()
    if (
        "less than desired gpu memory utilization" in lower
        or "out of memory" in lower
        or "cuda out of memory" in lower
    ):
        return (
            "\nHint: another process (often LM Studio) is using GPU memory. "
            "Stop it and run `make server-stop-hard && make server-start` again.\n"
        )
    return ""


def wait_for_vllm(cfg):
    label = "Atlas" if cfg.engine == "atlas" else "vLLM"
    section(f"Waiting for {label} to be ready")
    if cfg.engine == "atlas":
        info("Polling /v1/models — Atlas boots in <2 min (longer on first model download)")
    else:
        info(f"Polling /health + /v1/models — {_boot_time_hint(cfg)}")
    max_wait = _health_max_wait(cfg)
    elapsed = 0

    while elapsed < max_wait:
        status = _container_status(cfg)
        if status in ("exited", "dead", "missing"):
            logs = _container_logs_tail(cfg, lines=80)
            die(
                f"Container '{cfg.container_name}' is {status}."
                f"{_gpu_oom_hint(logs)}\n"
                f"Recent logs:\n{logs}"
            )
        restarts = _container_restart_count(cfg)
        if (status == "restarting" or restarts >= 2) and elapsed >= 10:
            logs = _container_logs_tail(cfg, lines=80)
            die(
                f"Container '{cfg.container_name}' is crash-looping "
                f"(status={status}, restarts={restarts})."
                f"{_gpu_oom_hint(logs)}\n"
                f"Recent logs:\n{logs}"
            )

        if _server_ready(cfg):
            label = "Atlas" if cfg.engine == "atlas" else "vLLM"
            ok(f"{label} ready after {elapsed}s")
            return

        if elapsed > 0 and elapsed % 15 == 0:
            hint = _latest_container_log_line(cfg)
            msg = f"Still waiting... ({elapsed}s) [container: {status}]"
            if hint:
                msg += f"\n    latest: {hint}"
            info(msg)
        _exit_on_shutdown(cfg)
        interval = _health_poll_interval(elapsed)
        if not _sleep(interval):
            _exit_on_shutdown(cfg)
        elapsed += interval

    die(
        f"{label} not ready after {max_wait}s.\n"
        f"Container status: {_container_status(cfg)}\n"
        f"Recent logs:\n{_container_logs_tail(cfg)}"
    )
