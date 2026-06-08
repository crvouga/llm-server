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


def _models_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read())
            return bool(data.get("data"))
    except Exception:
        return False


def _engine_ready(cfg) -> bool:
    return _models_ok(f"http://localhost:{cfg.service_port}/v1/models")


# Backward-compatible alias for Atlas engine module.
def _atlas_ready(cfg) -> bool:
    return _engine_ready(cfg)


def _gpu_oom_hint(cfg, logs: str) -> str:
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
    if "illegal instruction" in lower or "sigill" in lower:
        return (
            "\nHint: GB10/sm_121 PTX mismatch — try a GB10-tuned vLLM image "
            "(`VLLM_IMAGE=avarok/dgx-vllm-nvfp4-kernel:v22`) or disable "
            "speculative decoding (`VLLM_NO_SPECULATIVE=1`).\n"
        )
    if "not found in store" in lower and cfg.engine == "atlas":
        return (
            "\nHint: Atlas failed while mapping NVFP4 weights. For "
            "RedHatAI/Qwen3-Coder-Next-NVFP4 this usually means the attention "
            "weight-compat was not merged into the checkpoint shards — "
            "rerun `make server-start` (the launcher materializes missing BF16 "
            "Q/K/V tensors into model-00010-of-00010 automatically). "
            "If it persists after a fresh start, run "
            "`make server-stop && ENGINE_FORCE_RESTART=1 make server-start`, "
            "pull the latest image (`ATLAS_PULL=always make server-start`), "
            "or lower `ATLAS_MAX_SEQ_LEN` / set `ATLAS_NO_SPECULATIVE=1`.\n"
        )
    if "kv cache can hold at most" in lower and "max-batch-size" in lower:
        if cfg.engine == "atlas":
            return (
                "\nHint: 128K context uses most of the GB10 KV pool — lower "
                "`ATLAS_MAX_BATCH_SIZE` (default 6) or reduce `ATLAS_MAX_SEQ_LEN`. "
                "Atlas prints the exact limits in the error above.\n"
            )
        return (
            "\nHint: 128K context uses most of the GB10 KV pool — reduce "
            "`VLLM_MAX_MODEL_LEN` or lower `VLLM_GPU_MEM_UTIL`.\n"
        )
    if "out of memory" in lower and cfg.engine == "vllm":
        return (
            "\nHint: vLLM OOM on GB10 — lower `VLLM_GPU_MEM_UTIL` (default 0.60), "
            "reduce `VLLM_MAX_MODEL_LEN`, or set `VLLM_NO_SPECULATIVE=1`.\n"
        )
    return ""


def wait_for_engine(cfg):
    from .engine_dispatch import engine_label

    label = engine_label(cfg)
    section(f"Waiting for {label} to be ready")
    info(f"Polling /v1/models — {label} boots in ~1-2 min")
    max_wait = int(
        os.environ.get(
            "ENGINE_READY_TIMEOUT",
            os.environ.get("ATLAS_READY_TIMEOUT", "900"),
        )
    )
    elapsed = 0

    while elapsed < max_wait:
        status = _container_status(cfg)
        if status in ("exited", "dead", "missing"):
            logs = _container_logs_tail(cfg, lines=80)
            die(
                f"Container '{cfg.container_name}' is {status}."
                f"{_gpu_oom_hint(cfg, logs)}\n"
                f"Recent logs:\n{logs}"
            )
        restarts = _container_restart_count(cfg)
        if (status == "restarting" or restarts >= 2) and elapsed >= 10:
            logs = _container_logs_tail(cfg, lines=80)
            die(
                f"Container '{cfg.container_name}' is crash-looping "
                f"(status={status}, restarts={restarts})."
                f"{_gpu_oom_hint(cfg, logs)}\n"
                f"Recent logs:\n{logs}"
            )

        if _engine_ready(cfg):
            ok(f"{label} ready after {elapsed}s")
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
        f"{label} not ready after {max_wait}s.\n"
        f"Container status: {_container_status(cfg)}\n"
        f"Recent logs:\n{_container_logs_tail(cfg)}"
    )
