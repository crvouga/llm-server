"""Readiness probes + the boot wait loop."""

import json
import os
import urllib.request

from .console import die, info, ok, section
from .containers import (
    _container_logs_tail,
    _container_restart_count,
    _container_status,
    _latest_container_log_line,
)
from .runtime import _exit_on_shutdown, _sleep


def _atlas_models_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read())
            return bool(data.get("data"))
    except Exception:
        return False


def _atlas_ready(cfg) -> bool:
    return _atlas_models_ok(
        f"http://localhost:{cfg.atlas_port}/v1/models"
    )


def _gpu_oom_hint(logs: str) -> str:
    lower = logs.lower()
    if (
        "less than desired gpu memory utilization" in lower
        or "out of memory" in lower
        or "cuda out of memory" in lower
    ):
        return (
            "\nHint: another process (often LM Studio) is using GPU memory. "
            "Stop it and run `make server-stop && make server-start` again.\n"
        )
    if "not found in store" in lower:
        return (
            "\nHint: Atlas failed while mapping NVFP4 weights. For "
            "RedHatAI/Qwen3-Coder-Next-NVFP4 this usually means the attention "
            "weight-compat sidecar was not built — rerun `make server-start` "
            "(the launcher materializes missing BF16 Q/K/V tensors automatically). "
            "If it persists after a fresh start, run "
            "`make server-stop && ATLAS_FORCE_RESTART=1 make server-start`, "
            "pull the latest image (`ATLAS_PULL=always make server-start`), "
            "or lower `ATLAS_MAX_SEQ_LEN` / set `ATLAS_NO_SPECULATIVE=1`.\n"
        )
    return ""


def wait_for_engine(cfg):
    section("Waiting for Atlas to be ready")
    info("Polling /v1/models — Atlas boots in <2 min")
    max_wait = int(os.environ.get("ATLAS_READY_TIMEOUT", "900"))
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

        if _atlas_ready(cfg):
            ok(f"Atlas ready after {elapsed}s")
            return

        if elapsed > 0 and elapsed % 15 == 0:
            hint = _latest_container_log_line(cfg)
            msg = f"Still waiting... ({elapsed}s) [container: {status}]"
            if hint:
                msg += f"\n    latest: {hint}"
            info(msg)
        _exit_on_shutdown(cfg)
        interval = 2 if elapsed < 60 else 5
        if not _sleep(interval):
            _exit_on_shutdown(cfg)
        elapsed += interval

    die(
        f"Atlas not ready after {max_wait}s.\n"
        f"Container status: {_container_status(cfg)}\n"
        f"Recent logs:\n{_container_logs_tail(cfg)}"
    )
