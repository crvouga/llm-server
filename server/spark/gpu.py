"""GPU access flags + preflight (GB10 reports N/A in nvidia-smi)."""

import shutil
import subprocess

from .console import die, ok, section, warn


def _gpu_run_flags():
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


def precheck_gpu_available(cfg, docker_cmd):
    section("Precheck: GPU")
    if shutil.which("nvidia-smi"):
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True)
        if r.returncode == 0:
            ok(r.stdout.strip().splitlines()[0])
        else:
            warn("nvidia-smi failed — continuing, Docker GPU test is authoritative")
    if not _gpu_test(docker_cmd):
        die(
            "GPU not available inside Docker.\n"
            "  Check: nvidia-smi\n"
            "  Install: NVIDIA container toolkit"
        )
    ok("Docker GPU access OK")
