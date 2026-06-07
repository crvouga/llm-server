#!/usr/bin/env python3
"""
spark_serve.py — vLLM + DFlash + Cloudflare Tunnel for DGX Spark / GB10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Model:   Qwen3.6-35B-A3B (NVFP4, GB10-optimised) + DFlash speculative decoding
Target:  120-150 tok/s single-stream on coding workloads

Idempotent. Manages its own process group. Kill the script (Ctrl+C or
SIGTERM) and it cleans up everything it started: container + tunnel.

Usage:
    python3 server/server.py
    # or: DOPPLER_TOKEN=dp.st.xxx python3 server/server.py

Secrets via Doppler CLI (`doppler login` + `doppler setup`) or DOPPLER_TOKEN.
Doppler secrets (project=personal, config=dev):
    CLOUDFLARE_API_TOKEN   — Cloudflare API token
    CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID
    HF_TOKEN               — Hugging Face token (optional)
"""

import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── ANSI colours ──────────────────────────────────────────────────────────────
R = "\033[0;31m"
G = "\033[0;32m"
Y = "\033[1;33m"
C = "\033[0;36m"
B = "\033[1m"
X = "\033[0m"


def info(msg):
    print(f"{C}[•]{X} {msg}", flush=True)


def ok(msg):
    print(f"{G}[✓]{X} {msg}", flush=True)


def warn(msg):
    print(f"{Y}[!]{X} {msg}", flush=True)


def err(msg):
    print(f"{R}[✗]{X} {msg}", file=sys.stderr, flush=True)


def section(msg):
    print(f"\n{B}━━━  {msg}  ━━━{X}", flush=True)


def die(msg):
    err(msg)
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # Doppler
    doppler_token: str = ""
    doppler_project: str = "personal"
    doppler_config: str = "dev"

    # Secrets — populated from Doppler
    cf_api_token: str = ""
    cf_account_id: str = ""
    hf_token: str = ""

    # Cloudflare tunnel
    cf_tunnel_name: str = "spark-serve"

    # Models
    # Main:    AEON-7 heretic-NVFP4 — production-stable, correct vLLM key layout
    # Drafter: z-lab DFlash block-diffusion (must be post 2026-04-19 revision)
    # Flat layout under {model_dir}/{main,drafter} — predictable for vLLM flags
    model: str = "AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4"
    dflash_drafter: str = "z-lab/Qwen3.6-35B-A3B-DFlash"
    model_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "qwen36")

    # vLLM
    # Image: SM121-patched (8 patches, FlashInfer 0.6.8, Marlin GEMM enforcement)
    # ⚠️  max_num_seqs > 16 causes system freeze during torch.compile on GB10
    vllm_port: int = 8000
    max_model_len: int = 65536  # 65K: best tradeoff for agentic coding
    gpu_mem_util: float = 0.85
    max_num_seqs: int = 16  # hard ceiling on GB10
    dflash_num_spec_tokens: int = 15  # k=15 optimal for code (~78% acceptance)
    container_name: str = "vllm-qwen36-dflash"
    vllm_image: str = "ghcr.io/aeon-7/vllm-spark-omni-q36:v1.2"
    docker_cmd: list = field(default_factory=lambda: ["docker"])

    # Runtime
    helper_dir: Path = field(default_factory=lambda: Path.home() / ".spark-serve")


# ── Process registry ──────────────────────────────────────────────────────────
_managed: list = []
_managed_containers: list = []
_shutdown_requested = False
_cleanup_done = False


def register(proc):
    _managed.append(proc)
    return proc


def register_container(name):
    _managed_containers.append(name)


def _request_shutdown(*, force: bool = False) -> None:
    global _shutdown_requested
    if force or _shutdown_requested:
        print(f"\n{Y}[!]{X} Force quit", flush=True)
        os._exit(130)
    _shutdown_requested = True
    print(
        f"\n{Y}[!]{X} Shutting down... (Ctrl+C again to force quit)",
        flush=True,
    )


def _handle_sigint(signum, frame):
    _request_shutdown()


def _handle_sigterm(signum, frame):
    _request_shutdown()


def _sleep(seconds: float) -> bool:
    """Sleep in short chunks so Ctrl+C is felt within ~200ms. Returns False if interrupted."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _shutdown_requested:
            return False
        time.sleep(min(0.2, end - time.monotonic()))
    return True


def _exit_on_shutdown(cfg) -> None:
    if _shutdown_requested:
        cleanup(cfg)
        sys.exit(130)


def cleanup(cfg):
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    print(f"\n{B}━━━  Shutting down  ━━━{X}", flush=True)
    for proc in _managed:
        if proc.poll() is None:
            info(f"Terminating PID {proc.pid}...")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
    for name in _managed_containers:
        info(f"Stopping container '{name}'...")
        subprocess.run(
            [*cfg.docker_cmd, "stop", name], capture_output=True, timeout=30
        )
        subprocess.run(
            [*cfg.docker_cmd, "rm", name], capture_output=True, timeout=30
        )
    (cfg.helper_dir / "cloudflared.pid").unlink(missing_ok=True)
    ok("Clean shutdown complete.")


# ── Doppler ───────────────────────────────────────────────────────────────────
def _apply_doppler_secrets(cfg, secrets: dict, source: str) -> None:
    def require(key):
        val = secrets.get(key, "")
        if not val:
            die(
                f"Secret '{key}' not found in Doppler {cfg.doppler_project}/{cfg.doppler_config}"
            )
        return val

    cfg.cf_api_token = require("CLOUDFLARE_API_TOKEN")
    cfg.cf_account_id = require("CLOUDFLARE_ACCOUNT_ID")
    cfg.hf_token = secrets.get("HF_TOKEN", "")

    ok(f"Secrets loaded from {source} ({cfg.doppler_project}/{cfg.doppler_config})")
    if not cfg.hf_token:
        warn("HF_TOKEN not in Doppler — fine for public models")


def _fetch_doppler_secrets_via_api(cfg) -> dict:
    token = cfg.doppler_token or os.environ.get("DOPPLER_TOKEN", "")
    if not token:
        return {}

    url = (
        "https://api.doppler.com/v3/configs/config/secrets/download"
        f"?project={cfg.doppler_project}&config={cfg.doppler_config}&format=json"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        die(f"Doppler API error {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        die(f"Could not reach Doppler: {e.reason}")


def _fetch_doppler_secrets_via_cli(cfg) -> dict:
    if not shutil.which("doppler"):
        return {}

    result = subprocess.run(
        [
            "doppler",
            "secrets",
            "download",
            "--project",
            cfg.doppler_project,
            "--config",
            cfg.doppler_config,
            "--no-file",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        die(
            "Could not fetch secrets via Doppler CLI.\n"
            f"  Project: {cfg.doppler_project}  Config: {cfg.doppler_config}\n"
            "  Run: doppler login && doppler setup --project personal --config dev\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def fetch_doppler_secrets(cfg):
    section("Fetching secrets from Doppler")

    if os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        _apply_doppler_secrets(cfg, os.environ, "environment")
        return

    secrets = _fetch_doppler_secrets_via_api(cfg)
    if secrets:
        _apply_doppler_secrets(cfg, secrets, "Doppler API")
        return

    secrets = _fetch_doppler_secrets_via_cli(cfg)
    if secrets:
        _apply_doppler_secrets(cfg, secrets, "Doppler CLI")
        return

    die(
        "No Doppler credentials found.\n"
        "  Option 1: doppler login && doppler setup --project personal --config dev\n"
        "  Option 2: DOPPLER_TOKEN=dp.st.xxx (service token from https://dashboard.doppler.com)\n"
        f"  Project: {cfg.doppler_project}  Config: {cfg.doppler_config}"
    )


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def http_get(url, headers=None):
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def http_post(url, data, headers=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def cf_headers(cfg):
    return {
        "Authorization": f"Bearer {cfg.cf_api_token}",
        "Content-Type": "application/json",
    }


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


# ── Dependencies ──────────────────────────────────────────────────────────────
def _docker_reachable(argv):
    return (
        subprocess.run(
            [*argv, "info"],
            capture_output=True,
        ).returncode
        == 0
    )


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


def _ensure_nvidia_cdi():
    if Path("/etc/cdi/nvidia.yaml").exists() or not shutil.which("nvidia-ctk"):
        return
    info("Generating NVIDIA CDI specs (fixes --gpus all on newer Docker)...")
    run(["sudo", "mkdir", "-p", "/etc/cdi"])
    run(["sudo", "nvidia-ctk", "cdi", "generate", "--output=/etc/cdi/nvidia.yaml"])
    run(["sudo", "systemctl", "restart", "docker"])
    time.sleep(2)


def _resolve_docker_cmd():
    for argv in (["docker"], ["sudo", "docker"]):
        if _docker_reachable(argv):
            return argv

    if shutil.which("docker") and subprocess.run(
        ["systemctl", "is-active", "--quiet", "docker"],
        capture_output=True,
    ).returncode != 0:
        info("Docker daemon not running — starting...")
        start = subprocess.run(
            ["sudo", "systemctl", "start", "docker"],
            capture_output=True,
            text=True,
        )
        if start.returncode != 0:
            journal = subprocess.run(
                ["journalctl", "-u", "docker.service", "-n", "30", "--no-pager"],
                capture_output=True,
                text=True,
            )
            if "invalid database" in journal.stdout:
                info("BuildKit database corrupted — resetting...")
                run(["sudo", "rm", "-rf", "/var/lib/docker/buildkit"])
                run(["sudo", "systemctl", "reset-failed", "docker"])
                run(["sudo", "systemctl", "start", "docker"])
                time.sleep(2)
                for argv in (["docker"], ["sudo", "docker"]):
                    if _docker_reachable(argv):
                        return argv
            die(
                "Docker daemon failed to start. "
                "Check: systemctl status docker.service"
            )
        time.sleep(2)
        for argv in (["docker"], ["sudo", "docker"]):
            if _docker_reachable(argv):
                return argv

    die(
        "Cannot connect to Docker. Ensure the daemon is running "
        "(sudo systemctl start docker) or add your user to the docker group."
    )


def _install_nvidia_container_toolkit():
    info("NVIDIA container toolkit not found — installing...")
    run(
        [
            "bash",
            "-c",
            "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey "
            "| sudo gpg --batch --yes --dearmor "
            "-o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg",
        ]
    )
    run(
        [
            "bash",
            "-c",
            "curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list "
            "| sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' "
            "| sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list",
        ]
    )
    run(["sudo", "apt-get", "update", "-qq"])
    run(["sudo", "apt-get", "install", "-y", "-q", "nvidia-container-toolkit"])


def ensure_docker(cfg):
    section("Checking Docker")

    if not shutil.which("docker"):
        info("Docker not found — installing...")
        run(["bash", "-c", "curl -fsSL https://get.docker.com | sudo sh"])
        run(["sudo", "usermod", "-aG", "docker", os.environ["USER"]])
        warn(
            f"Added {os.environ['USER']} to docker group — may need re-login on first install"
        )
    else:
        r = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        ok(r.stdout.strip())

    docker_cmd = _resolve_docker_cmd()
    _ensure_nvidia_cdi()

    if _gpu_test(docker_cmd):
        ok("NVIDIA container toolkit working")
        cfg.docker_cmd = docker_cmd
        return docker_cmd

    if shutil.which("nvidia-ctk"):
        info("NVIDIA container toolkit installed — configuring runtime...")
    else:
        _install_nvidia_container_toolkit()

    run(["sudo", "nvidia-ctk", "runtime", "configure", "--runtime=docker"])
    _ensure_nvidia_cdi()
    run(["sudo", "systemctl", "restart", "docker"])
    time.sleep(2)
    docker_cmd = _resolve_docker_cmd()

    if not _gpu_test(docker_cmd):
        die(
            "Docker GPU access failed. "
            "Check NVIDIA drivers (nvidia-smi) and container toolkit."
        )

    ok("NVIDIA container toolkit working")
    cfg.docker_cmd = docker_cmd
    return docker_cmd


def ensure_cloudflared():
    section("Checking cloudflared")
    if shutil.which("cloudflared"):
        r = subprocess.run(["cloudflared", "--version"], capture_output=True, text=True)
        ok(r.stdout.strip())
        return

    arch = platform.machine()
    cf_arch = {"aarch64": "arm64", "x86_64": "amd64"}.get(arch)
    if not cf_arch:
        die(f"Unsupported arch for cloudflared: {arch}")

    info(f"cloudflared not found — installing for {arch}...")
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{cf_arch}.deb"
    tmp = tempfile.mktemp(suffix=".deb")
    run(["curl", "-fsSL", url, "-o", tmp])
    run(["sudo", "dpkg", "-i", tmp])
    os.unlink(tmp)
    ok("cloudflared installed")


def ensure_git_lfs():
    section("Checking git-lfs")
    if shutil.which("git-lfs"):
        r = subprocess.run(["git-lfs", "version"], capture_output=True, text=True)
        ok(r.stdout.strip())
        return
    info("git-lfs not found — installing...")
    run(["sudo", "apt-get", "install", "-y", "-q", "git-lfs"])
    run(["git", "lfs", "install"])
    ok("git-lfs installed")


# ── Cloudflare tunnel (API-managed) ───────────────────────────────────────────
def ensure_cf_tunnel(cfg):
    section("Cloudflare tunnel (API)")
    base = (
        f"https://api.cloudflare.com/client/v4/accounts/{cfg.cf_account_id}/cfd_tunnel"
    )
    hdrs = cf_headers(cfg)

    resp = http_get(f"{base}?name={cfg.cf_tunnel_name}&is_deleted=false", hdrs)
    tunnels = resp.get("result", [])

    if tunnels:
        tunnel_id = tunnels[0]["id"]
        ok(f"Reusing tunnel '{cfg.cf_tunnel_name}' ({tunnel_id})")
    else:
        info(f"Creating tunnel '{cfg.cf_tunnel_name}'...")
        resp = http_post(
            base,
            {"name": cfg.cf_tunnel_name, "tunnel_secret": os.urandom(32).hex()},
            hdrs,
        )
        tunnel_id = resp["result"]["id"]
        ok(f"Created tunnel '{cfg.cf_tunnel_name}' ({tunnel_id})")

    tok = http_get(f"{base}/{tunnel_id}/token", hdrs)
    return tok["result"]


# ── Model download ────────────────────────────────────────────────────────────
# Flat layout — predictable paths passed directly to vLLM:
#   {model_dir}/main    — AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4  (~26 GB)
#   {model_dir}/drafter — z-lab/Qwen3.6-35B-A3B-DFlash           (~870 MB)


def _resolve_model_dir() -> Path:
    if env_dir := os.environ.get("MODEL_DIR"):
        return Path(env_dir).expanduser()
    opt = Path("/opt/qwen36")
    if opt.exists() and os.access(opt, os.W_OK | os.X_OK):
        return opt
    return Path.home() / ".cache" / "qwen36"


def _ensure_model_dir(cfg):
    try:
        cfg.model_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        parent = str(cfg.model_dir)
        if not parent.startswith("/opt/"):
            die(f"Cannot create model directory: {cfg.model_dir}")
        info(f"Creating {cfg.model_dir} with sudo...")
        run(["sudo", "mkdir", "-p", parent])
        run(["sudo", "chown", f"{os.environ['USER']}:{os.environ['USER']}", parent])
        cfg.model_dir.mkdir(parents=True, exist_ok=True)


def _model_path(cfg):
    return cfg.model_dir / "main"


def _drafter_path(cfg):
    return cfg.model_dir / "drafter"


def ensure_models(cfg, docker_cmd):
    section("Checking models")
    info(f"Model dir: {cfg.model_dir}")
    _ensure_model_dir(cfg)

    def download_if_missing(repo, local_dir, size_hint):
        if local_dir.exists() and any(local_dir.glob("*.safetensors")):
            ok(f"Already cached: {repo}")
            return
        local_dir.mkdir(parents=True, exist_ok=True)
        info(f"Downloading {repo}  ({size_hint})")
        py_cmd = (
            "from huggingface_hub import snapshot_download; "
            "snapshot_download("
            "'" + repo + "', "
            "local_dir='" + str(local_dir) + "', "
            "ignore_patterns=['*.pt','*.bin','*.msgpack']"
            ")"
        )
        bash_cmd = (
            "pip install -q huggingface_hub && "
            'HF_XET_HIGH_PERFORMANCE=1 python -c "' + py_cmd + '"'
        )
        run(
            [
                *docker_cmd,
                "run",
                "--rm",
                "-v",
                str(cfg.model_dir) + ":" + str(cfg.model_dir),
                "-e",
                "HF_TOKEN=" + cfg.hf_token,
                "-e",
                "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
                "-e",
                "HF_XET_HIGH_PERFORMANCE=1",
                "python:3.11-slim",
                "bash",
                "-c",
                bash_cmd,
            ]
        )
        ok(f"Downloaded: {repo}")

    download_if_missing(cfg.model, _model_path(cfg), "~26 GB NVFP4 — grab a coffee")
    download_if_missing(
        cfg.dflash_drafter, _drafter_path(cfg), "~870 MB DFlash drafter"
    )


# ── vLLM container ────────────────────────────────────────────────────────────
def pull_vllm_image(cfg, docker_cmd):
    section("Pulling vLLM image")
    info(f"Image: {cfg.vllm_image}  (~9 GB on first pull)")
    run([*docker_cmd, "pull", cfg.vllm_image])
    ok("Image ready")


def _query_cuda_memory(docker_cmd, image: str):
    """GB10 reports N/A in nvidia-smi; query CUDA's view from inside a GPU container."""
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
            return int(free_b), int(total_b)
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


def _check_gpu_memory(cfg, docker_cmd):
    section("Checking GPU memory")
    mem = _query_cuda_memory(docker_cmd, cfg.vllm_image)
    if not mem:
        warn("Could not query CUDA memory — skipping preflight check")
        return

    free_b, total_b = mem
    free_gib = free_b / (1024**3)
    total_gib = total_b / (1024**3)
    required_gib = total_gib * cfg.gpu_mem_util
    others = _gpu_compute_processes()

    if free_gib >= required_gib:
        ok(
            f"GPU memory OK: {free_gib:.1f}/{total_gib:.1f} GiB free "
            f"(budget {required_gib:.1f} GiB at {cfg.gpu_mem_util:.0%})"
        )
        return

    max_util = (free_gib / total_gib) * 0.98
    if max_util >= 0.35:
        warn(
            f"Only {free_gib:.1f}/{total_gib:.1f} GiB GPU memory free "
            f"(need {required_gib:.1f} GiB at {cfg.gpu_mem_util:.0%})"
        )
        if others:
            for line in others:
                warn(f"  GPU process: {line}")
        cfg.gpu_mem_util = round(max_util - 0.01, 2)
        warn(f"Lowering --gpu-memory-utilization to {cfg.gpu_mem_util:.2f}")
        return

    msg = (
        f"Insufficient GPU memory: {free_gib:.1f}/{total_gib:.1f} GiB free, "
        f"but vLLM needs ~{required_gib:.1f} GiB at {cfg.gpu_mem_util:.0%} utilization."
    )
    if others:
        msg += "\nStop these GPU processes first:\n  " + "\n  ".join(others)
    msg += (
        "\nDGX Spark has one GPU — only one large model can run at a time. "
        "Stop LM Studio (or other GPU workloads), then retry."
    )
    die(msg)


def stop_existing_container(cfg, docker_cmd):
    result = subprocess.run(
        [*docker_cmd, "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if cfg.container_name in result.stdout.splitlines():
        status = subprocess.run(
            [
                *docker_cmd,
                "inspect",
                "--format",
                "{{.State.Status}}",
                cfg.container_name,
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if status == "running":
            info(f"Stopping existing container '{cfg.container_name}'...")
            run([*docker_cmd, "stop", cfg.container_name])
        run([*docker_cmd, "rm", cfg.container_name])


def start_vllm(cfg, docker_cmd):
    section("Starting vLLM + DFlash  [Qwen3.6-35B-A3B NVFP4, k=15]")
    info("Target: 120-150 tok/s on coding workloads via DFlash speculative decoding")
    info("CUDA graph capture takes 5-10 min on first boot — this is normal")

    stop_existing_container(cfg, docker_cmd)
    register_container(cfg.container_name)

    # DFlash speculative config — drafter at container-internal path
    spec_config = json.dumps(
        {
            "method": "dflash",
            "model": "/models/drafter",
            "num_speculative_tokens": cfg.dflash_num_spec_tokens,
        }
    )

    run(
        [
            *docker_cmd,
            "run",
            "-d",
            "--name",
            cfg.container_name,
            *_gpu_run_flags(),
            "--network",
            "host",
            "--ipc",
            "host",
            "--ulimit",
            "memlock=-1:-1",
            "--restart",
            "unless-stopped",
            # Mount model weights at fixed container paths (read-only)
            "-v",
            str(_model_path(cfg)) + ":/models/main:ro",
            "-v",
            str(_drafter_path(cfg)) + ":/models/drafter:ro",
            "-e",
            "VLLM_ALLOW_LONG_MAX_MODEL_LEN=1",
            "-e",
            "TORCH_MATMUL_PRECISION=high",
            "-e",
            "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
            "-e",
            "NVIDIA_FORWARD_COMPAT=1",
            "-e",
            "VLLM_TEST_FORCE_FP8_MARLIN=1",
            "-e",
            "HF_TOKEN=" + cfg.hf_token,
            "-e",
            "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
            cfg.vllm_image,
            # Match AEON-7 docker-compose.yml — NVFP4 needs compressed-tensors
            "vllm",
            "serve",
            "/models/main",
            "--served-model-name",
            "qwen3.6-35b",
            "--host",
            "0.0.0.0",
            "--port",
            str(cfg.vllm_port),
            "--tensor-parallel-size",
            "1",
            "--dtype",
            "auto",
            "--quantization",
            "compressed-tensors",
            "--max-model-len",
            str(cfg.max_model_len),
            "--max-num-seqs",
            str(cfg.max_num_seqs),
            "--max-num-batched-tokens",
            "32768",
            "--gpu-memory-utilization",
            str(cfg.gpu_mem_util),
            "--enable-chunked-prefill",
            "--enable-prefix-caching",
            "--load-format",
            "safetensors",
            "--trust-remote-code",
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            "qwen3_coder",
            "--reasoning-parser",
            "qwen3",
            "--attention-backend",
            "flash_attn",
            "--speculative-config",
            spec_config,
        ]
    )
    ok(f"Container '{cfg.container_name}' started")


def _container_status(cfg):
    r = subprocess.run(
        [
            *cfg.docker_cmd,
            "inspect",
            "--format",
            "{{.State.Status}}",
            cfg.container_name,
        ],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else "missing"


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


def wait_for_vllm(cfg):
    section("Waiting for vLLM to be ready")
    info("Polling /health — CUDA graph capture can take up to 10 min on first boot...")
    url = f"http://localhost:{cfg.vllm_port}/health"
    max_wait = 600
    elapsed = 0

    while elapsed < max_wait:
        status = _container_status(cfg)
        if status in ("exited", "dead", "missing"):
            die(
                f"Container '{cfg.container_name}' is {status}.\n"
                f"Recent logs:\n{_container_logs_tail(cfg)}"
            )
        restarts = _container_restart_count(cfg)
        if (status == "restarting" or restarts >= 2) and elapsed >= 10:
            logs = _container_logs_tail(cfg, lines=80)
            hint = ""
            if "less than desired gpu memory utilization" in logs.lower():
                hint = (
                    "\nHint: another process (often LM Studio) is using GPU memory. "
                    "Stop it and run `make kill && make run` again.\n"
                )
            die(
                f"Container '{cfg.container_name}' is crash-looping "
                f"(status={status}, restarts={restarts}).{hint}\n"
                f"Recent logs:\n{logs}"
            )

        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    ok(f"vLLM healthy after {elapsed}s")
                    return
        except Exception:
            pass
        if elapsed > 0 and elapsed % 30 == 0:
            info(f"Still waiting... ({elapsed}s) [container: {status}]")
        _exit_on_shutdown(cfg)
        if not _sleep(5):
            _exit_on_shutdown(cfg)
        elapsed += 5

    die(
        f"vLLM not healthy after {max_wait}s.\n"
        f"Container status: {_container_status(cfg)}\n"
        f"Recent logs:\n{_container_logs_tail(cfg)}"
    )


def warmup_vllm(cfg):
    info("Warming up (2 dummy requests for CUDA graph specialisation)...")
    url = f"http://localhost:{cfg.vllm_port}/v1/completions"
    payload = json.dumps(
        {"model": "qwen3.6-35b", "prompt": "hi", "max_tokens": 1}
    ).encode()
    for _ in range(2):
        try:
            req = urllib.request.Request(url, data=payload)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=60):
                pass
        except Exception:
            pass
    ok("Warmup done — server at full speed")


# ── Cloudflare tunnel process ─────────────────────────────────────────────────
def _stop_spark_tunnel(cfg):
    """Stop only this server's token-based tunnel, not other cloudflared services."""
    pid_file = cfg.helper_dir / "cloudflared.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
        except (OSError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)
    subprocess.run(
        ["pkill", "-f", "cloudflared tunnel --no-autoupdate run --token"],
        capture_output=True,
    )


def start_cf_tunnel(cfg, tunnel_token):
    section("Starting Cloudflare tunnel")
    cf_log = cfg.helper_dir / "cloudflare-tunnel.log"
    cfg.helper_dir.mkdir(parents=True, exist_ok=True)

    _stop_spark_tunnel(cfg)
    time.sleep(1)

    log_file = open(cf_log, "w")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token],
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    (cfg.helper_dir / "cloudflared.pid").write_text(str(proc.pid))
    register(proc)

    info("Waiting for tunnel to connect...")
    time.sleep(6)

    if proc.poll() is not None:
        die(f"cloudflared exited.\nLog:\n{cf_log.read_text()[-1000:]}")

    ok(f"Cloudflare tunnel running (PID {proc.pid})")

    log_text = cf_log.read_text()
    for word in log_text.split():
        if word.startswith("https://") and (
            "cloudflare.com" in word or "trycloudflare.com" in word
        ):
            return word.strip()
    return None


# ── Helper scripts ────────────────────────────────────────────────────────────
def write_helpers(cfg):
    section("Writing helper scripts")
    d = cfg.helper_dir
    cf_log = d / "cloudflare-tunnel.log"
    d.mkdir(parents=True, exist_ok=True)

    (d / "logs.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f'echo "=== vLLM (last 50 lines) ==="\n'
        f"docker logs --tail 50 {cfg.container_name}\n"
        f'echo ""\n'
        f'echo "=== Cloudflare tunnel (last 20 lines) ==="\n'
        f"tail -20 {cf_log}\n"
    )
    (d / "stop.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"docker stop {cfg.container_name} 2>/dev/null || true\n"
        f"docker rm   {cfg.container_name} 2>/dev/null || true\n"
        f'if [ -f "{d}/cloudflared.pid" ]; then\n'
        f'  kill "$(cat "{d}/cloudflared.pid")" 2>/dev/null || true\n'
        f'  rm -f "{d}/cloudflared.pid"\n'
        f"fi\n"
        f'pkill -f "cloudflared tunnel --no-autoupdate run --token" 2>/dev/null || true\n'
        f'echo "Done."\n'
    )
    (d / "status.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"G='\\033[0;32m'; R='\\033[0;31m'; X='\\033[0m'\n"
        f"docker ps --filter name={cfg.container_name} --format 'table {{{{.Names}}}}\\t{{{{.Status}}}}'\n"
        f"curl -sf http://localhost:{cfg.vllm_port}/health >/dev/null 2>&1 "
        f'&& echo -e "${{G}}● vLLM healthy:{cfg.vllm_port}${{X}}" '
        f'|| echo -e "${{R}}✗ vLLM not responding${{X}}"\n'
        f"curl -s http://localhost:{cfg.vllm_port}/v1/models "
        f"| python3 -c \"import sys,json; [print('  •', m['id']) for m in json.load(sys.stdin).get('data',[])]\" "
        f"2>/dev/null || echo '(not ready)'\n"
        f'if [ -f "{d}/cloudflared.pid" ] && kill -0 "$(cat "{d}/cloudflared.pid")" 2>/dev/null; then\n'
        f'  echo -e "${{G}}● tunnel running${{X}}"\n'
        f"else\n"
        f'  echo -e "${{R}}✗ tunnel not running${{X}}"\n'
        f"fi\n"
    )
    for f in d.glob("*.sh"):
        f.chmod(0o755)
    ok(f"Helpers written to {d}/")


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary(cfg, cf_url):
    section("🚀 Server is live")
    d = cfg.helper_dir
    print(
        f"""
  {B}Model:{X}    {cfg.model}
  {B}DFlash:{X}   {cfg.dflash_drafter} (k={cfg.dflash_num_spec_tokens})
  {B}Target:{X}   120-150 tok/s on coding  |  300+ tok/s aggregate at concurrency 16
  {B}Context:{X}  {cfg.max_model_len} tokens  |  {B}Max seqs:{X} {cfg.max_num_seqs}
 
  {B}Local API:{X}
    http://localhost:{cfg.vllm_port}/v1
 
  {B}Public API (Cloudflare):{X}
    {G}{cf_url + "/v1" if cf_url else "— check Cloudflare Zero Trust dashboard"}{X}
 
  {B}Agent config:{X}
    base_url  = http://localhost:{cfg.vllm_port}/v1
    api_key   = not-required
    model     = qwen3.6-35b
 
  {B}Commands:{X}
    {d}/status.sh
    {d}/logs.sh
    {d}/stop.sh
    docker logs -f {cfg.container_name}
"""
    )
    warn("Keep this process running — Ctrl+C stops tunnel + container cleanly.")
    warn("First novel request shape takes ~30s for CUDA graph specialisation.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    cfg.doppler_token = os.environ.get("DOPPLER_TOKEN", "")

    if platform.machine() != "aarch64":
        warn(
            f"Expected aarch64 (GB10), got {platform.machine()} — optimisations may not apply"
        )

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        fetch_doppler_secrets(cfg)
        _exit_on_shutdown(cfg)

        docker_cmd = ensure_docker(cfg)
        _exit_on_shutdown(cfg)
        ensure_cloudflared()
        ensure_git_lfs()
        pull_vllm_image(cfg, docker_cmd)
        _exit_on_shutdown(cfg)
        ensure_models(cfg, docker_cmd)
        _check_gpu_memory(cfg, docker_cmd)
        start_vllm(cfg, docker_cmd)
        wait_for_vllm(cfg)
        warmup_vllm(cfg)
        _exit_on_shutdown(cfg)

        tunnel_token = ensure_cf_tunnel(cfg)
        cf_url = start_cf_tunnel(cfg, tunnel_token)

        write_helpers(cfg)
        print_summary(cfg, cf_url)

        info("Running. Press Ctrl+C to stop everything.")
        while not _shutdown_requested:
            # Watchdog: restart container if it exits unexpectedly
            r = subprocess.run(
                [
                    *docker_cmd,
                    "inspect",
                    "--format",
                    "{{.State.Status}}",
                    cfg.container_name,
                ],
                capture_output=True,
                text=True,
            )
            if r.stdout.strip() not in ("running", ""):
                warn("Container exited unexpectedly — restarting...")
                start_vllm(cfg, docker_cmd)
                wait_for_vllm(cfg)
                warmup_vllm(cfg)
            if not _sleep(30):
                break

    except KeyboardInterrupt:
        _request_shutdown()
    except SystemExit:
        raise
    except Exception as e:
        err(f"Unexpected error: {e}")
        cleanup(cfg)
        raise
    finally:
        if _shutdown_requested:
            cleanup(cfg)


if __name__ == "__main__":
    main()
