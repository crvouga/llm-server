"""GPU access flags + memory preflight (GB10 reports N/A in nvidia-smi)."""

import os
import shutil
import subprocess
from typing import Optional

from .console import die, info, ok, section, warn
from .containers import _container_status

_gpu_probe_cache: Optional[tuple[int, int]] = None


def _gpu_run_flags():
    # --gpus all relies on CDI specs that are often missing on fresh Spark installs.
    # The nvidia runtime is configured in /etc/docker/daemon.json and works reliably.
    return [
        "--runtime",
        "nvidia",
        "-e",
        "NVIDIA_VISIBLE_DEVICES=all",
        "-e",
        "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
    ]


def _gpu_test(argv):
    r = subprocess.run(
        [
            *argv,
            "run",
            "--rm",
            *_gpu_run_flags(),
            "nvidia/cuda:12.0.0-base-ubuntu22.04",
            "nvidia-smi",
        ],
        capture_output=True,
        text=True,
    )
    out = r.stdout + r.stderr
    return r.returncode == 0 and "NVIDIA" in out


def _probe_gpu(docker_cmd, image: str) -> Optional[tuple[int, int]]:
    """GB10 reports N/A in nvidia-smi; query CUDA's view from inside a GPU container."""
    global _gpu_probe_cache
    if _gpu_probe_cache is not None:
        return _gpu_probe_cache

    r = subprocess.run(
        [
            *docker_cmd,
            "run",
            "--rm",
            *_gpu_run_flags(),
            image,
            "python3",
            "-c",
            "import torch; f,t=torch.cuda.mem_get_info(); print(f'{f},{t}')",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if "," in line and line.split(",", 1)[0].isdigit():
            free_b, total_b = line.split(",", 1)
            _gpu_probe_cache = (int(free_b), int(total_b))
            return _gpu_probe_cache
    return None


def _gpu_compute_processes():
    r = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_gpu_memory",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def precheck_gpu_available(cfg, docker_cmd):
    section("Precheck: GPU")
    if shutil.which("nvidia-smi"):
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True)
        if r.returncode == 0:
            ok(r.stdout.strip().splitlines()[0])
        else:
            warn("nvidia-smi failed — continuing, Docker GPU test is authoritative")
    if cfg.engine == "atlas":
        # Atlas image has no torch for the CUDA probe; a plain GPU test is enough.
        if not _gpu_test(docker_cmd):
            die(
                "GPU not available inside Docker.\n"
                "  Check: nvidia-smi\n"
                "  Install: NVIDIA container toolkit"
            )
        ok("Docker GPU access OK")
        return
    mem = _probe_gpu(docker_cmd, cfg.vllm_image)
    if mem is None and not _gpu_test(docker_cmd):
        die(
            "GPU not available inside Docker.\n"
            "  Check: nvidia-smi\n"
            "  Install: NVIDIA container toolkit"
        )
    ok("Docker GPU access OK")


def _check_gpu_memory(cfg, docker_cmd):
    section("Checking GPU memory")
    if _container_status(cfg) == "running":
        ok(
            f"GPU in use by warm container '{cfg.container_name}' — reusing "
            "(skip memory preflight)"
        )
        cfg.gpu_exclusive = False
        return
    mem = _probe_gpu(docker_cmd, cfg.vllm_image)
    if not mem:
        warn("Could not query CUDA memory — skipping preflight check")
        cfg.gpu_exclusive = False
        return

    free_b, total_b = mem
    free_gib = free_b / (1024**3)
    total_gib = total_b / (1024**3)
    required_gib = total_gib * cfg.gpu_mem_util
    others = _gpu_compute_processes()
    allow_sharing = os.environ.get("VLLM_ALLOW_GPU_SHARING", "").lower() in (
        "1",
        "true",
        "yes",
    )

    if free_gib >= required_gib:
        cfg.gpu_exclusive = True
        ok(
            f"GPU memory OK: {free_gib:.1f}/{total_gib:.1f} GiB free "
            f"(budget {required_gib:.1f} GiB at {cfg.gpu_mem_util:.0%})"
        )
        return

    msg = (
        f"Insufficient GPU memory: {free_gib:.1f}/{total_gib:.1f} GiB free, "
        f"but vLLM needs ~{required_gib:.1f} GiB at {cfg.gpu_mem_util:.0%} utilization."
    )
    if others:
        msg += "\nStop these GPU processes first:\n  " + "\n  ".join(others)
    msg += (
        "\nDGX Spark has one GPU — only one large model can run at a time. "
        "Stop LM Studio (or other GPU workloads), then run `make server-start` again."
    )
    max_util = (free_gib / total_gib) * 0.98
    if max_util >= 0.35:
        msg += (
            f"\nOr share the GPU with a lower memory budget: "
            f"VLLM_ALLOW_GPU_SHARING=1 make server-start "
            f"(would use ~{max_util - 0.01:.0%} utilization, ~{total_gib * (max_util - 0.01):.1f} GiB)."
        )

    if allow_sharing:
        if max_util < 0.35:
            die(msg)
        warn(msg)
        cfg.gpu_exclusive = False
        cfg.gpu_mem_util = round(max_util - 0.01, 2)
        warn(
            f"VLLM_ALLOW_GPU_SHARING=1 — lowering --gpu-memory-utilization "
            f"to {cfg.gpu_mem_util:.2f}"
        )
        return

    die(msg)
