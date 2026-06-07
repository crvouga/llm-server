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
    # Flat layout under /opt/qwen36/{main,drafter} — predictable for vLLM flags
    model: str = "AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4"
    dflash_drafter: str = "z-lab/Qwen3.6-35B-A3B-DFlash"
    model_dir: Path = field(default_factory=lambda: Path("/opt/qwen36"))

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

    # Runtime
    helper_dir: Path = field(default_factory=lambda: Path.home() / ".spark-serve")


# ── Process registry ──────────────────────────────────────────────────────────
_managed: list = []
_managed_containers: list = []


def register(proc):
    _managed.append(proc)
    return proc


def register_container(name):
    _managed_containers.append(name)


def cleanup(cfg):
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
        subprocess.run(["docker", "stop", name], capture_output=True)
        subprocess.run(["docker", "rm", name], capture_output=True)
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
def ensure_docker(cfg):
    section("Checking Docker")
    docker_cmd = "docker"

    if not shutil.which("docker"):
        info("Docker not found — installing...")
        run(["bash", "-c", "curl -fsSL https://get.docker.com | sudo sh"])
        run(["sudo", "usermod", "-aG", "docker", os.environ["USER"]])
        warn(
            f"Added {os.environ['USER']} to docker group — may need re-login on first install"
        )
        docker_cmd = "sudo docker"
    else:
        r = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        ok(r.stdout.strip())

    # NVIDIA container toolkit
    test = subprocess.run(
        [
            docker_cmd,
            "run",
            "--rm",
            "--gpus",
            "all",
            "nvidia/cuda:12.0-base-ubuntu22.04",
            "nvidia-smi",
        ],
        capture_output=True,
    )
    if test.returncode != 0:
        info("NVIDIA container toolkit not found — installing...")
        run(
            [
                "bash",
                "-c",
                "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey "
                "| sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg",
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
        run(["sudo", "nvidia-ctk", "runtime", "configure", "--runtime=docker"])
        run(["sudo", "systemctl", "restart", "docker"])
        ok("NVIDIA container toolkit installed")
    else:
        ok("NVIDIA container toolkit working")

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
#   /opt/qwen36/main    — AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4  (~26 GB)
#   /opt/qwen36/drafter — z-lab/Qwen3.6-35B-A3B-DFlash           (~870 MB)


def _model_path(cfg):
    return cfg.model_dir / "main"


def _drafter_path(cfg):
    return cfg.model_dir / "drafter"


def ensure_models(cfg, docker_cmd):
    section("Checking models")
    cfg.model_dir.mkdir(parents=True, exist_ok=True)

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
            "pip install -q 'huggingface_hub[hf_transfer]' && "
            'HF_HUB_ENABLE_HF_TRANSFER=1 python -c "' + py_cmd + '"'
        )
        run(
            [
                docker_cmd,
                "run",
                "--rm",
                "-v",
                str(cfg.model_dir) + ":" + str(cfg.model_dir),
                "-e",
                "HF_TOKEN=" + cfg.hf_token,
                "-e",
                "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
                "-e",
                "HF_HUB_ENABLE_HF_TRANSFER=1",
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
    run([docker_cmd, "pull", cfg.vllm_image])
    ok("Image ready")


def stop_existing_container(cfg, docker_cmd):
    result = subprocess.run(
        [docker_cmd, "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if cfg.container_name in result.stdout.splitlines():
        status = subprocess.run(
            [
                docker_cmd,
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
            run([docker_cmd, "stop", cfg.container_name])
        run([docker_cmd, "rm", cfg.container_name])


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
            docker_cmd,
            "run",
            "-d",
            "--name",
            cfg.container_name,
            "--gpus",
            "all",
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
            "HF_TOKEN=" + cfg.hf_token,
            "-e",
            "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
            cfg.vllm_image,
            # vLLM serve args passed after image name
            "vllm",
            "serve",
            "/models/main",
            "--served-model-name",
            "qwen3.6-35b",
            "--port",
            str(cfg.vllm_port),
            "--host",
            "0.0.0.0",
            "--trust-remote-code",
            "--max-model-len",
            str(cfg.max_model_len),
            "--max-num-seqs",
            str(cfg.max_num_seqs),
            "--max-num-batched-tokens",
            "32768",
            "--gpu-memory-utilization",
            str(cfg.gpu_mem_util),
            "--attention-backend",
            "flash_attn",
            "--enable-prefix-caching",  # speeds up repeated system prompts in agents
            "--enable-auto-tool-choice",  # agentic tool calling
            "--tool-call-parser",
            "qwen3_coder",
            "--speculative-config",
            spec_config,
            "--disable-log-requests",  # cleaner output
        ]
    )
    ok(f"Container '{cfg.container_name}' started")


def wait_for_vllm(cfg):
    section("Waiting for vLLM to be ready")
    info("Polling /health — CUDA graph capture can take up to 10 min on first boot...")
    url = f"http://localhost:{cfg.vllm_port}/health"
    max_wait = 600
    elapsed = 0

    while elapsed < max_wait:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    ok(f"vLLM healthy after {elapsed}s")
                    return
        except Exception:
            pass
        if elapsed > 0 and elapsed % 30 == 0:
            info(f"Still waiting... ({elapsed}s)")
        time.sleep(5)
        elapsed += 5

    die(
        f"vLLM not healthy after {max_wait}s.\n  Check: docker logs {cfg.container_name}"
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
def start_cf_tunnel(cfg, tunnel_token):
    section("Starting Cloudflare tunnel")
    cf_log = cfg.helper_dir / "cloudflare-tunnel.log"
    cfg.helper_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["pkill", "-f", "cloudflared tunnel run"], capture_output=True)
    time.sleep(1)

    log_file = open(cf_log, "w")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token],
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
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
        f'pkill -f "cloudflared tunnel run" 2>/dev/null || true\n'
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
        f'pgrep -f "cloudflared tunnel run" >/dev/null '
        f'&& echo -e "${{G}}● tunnel running${{X}}" || echo -e "${{R}}✗ tunnel not running${{X}}"\n'
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
    cfg.doppler_token = os.environ.get("DOPPLER_TOKEN", "")

    if platform.machine() != "aarch64":
        warn(
            f"Expected aarch64 (GB10), got {platform.machine()} — optimisations may not apply"
        )

    def _sig(signum, frame):
        print(f"\n{Y}[!]{X} Signal {signum} received", flush=True)
        cleanup(cfg)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        fetch_doppler_secrets(cfg)

        docker_cmd = ensure_docker(cfg)
        ensure_cloudflared()
        ensure_git_lfs()
        pull_vllm_image(cfg, docker_cmd)
        ensure_models(cfg, docker_cmd)
        start_vllm(cfg, docker_cmd)
        wait_for_vllm(cfg)
        warmup_vllm(cfg)

        tunnel_token = ensure_cf_tunnel(cfg)
        cf_url = start_cf_tunnel(cfg, tunnel_token)

        write_helpers(cfg)
        print_summary(cfg, cf_url)

        info("Running. Press Ctrl+C to stop everything.")
        while True:
            # Watchdog: restart container if it exits unexpectedly
            r = subprocess.run(
                [
                    docker_cmd,
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
            time.sleep(30)

    except SystemExit:
        raise
    except Exception as e:
        err(f"Unexpected error: {e}")
        cleanup(cfg)
        raise


if __name__ == "__main__":
    main()
