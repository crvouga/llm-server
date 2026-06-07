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
    CLOUDFLARE_API_TOKEN   — Cloudflare API token (required; tunnels, WAF, Workers)
    CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID (required)
    HF_TOKEN               — Hugging Face token (optional)

All prechecks run before vLLM starts so config errors fail in seconds, not minutes.
"""

import hashlib
import json
import math
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

_CONFIG_HASH_LABEL = "spark-serve.config-hash"
_SERVED_MODEL = "qwen3.6-35b"
_WARMUP_PROMPT = (
    "def fibonacci(n: int) -> int:\n"
    "    if n <= 1:\n"
    "        return n\n"
    "    return fibonacci(n - 1) + fibonacci(n - 2)\n"
)
_gpu_probe_cache: Optional[tuple[int, int]] = None

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


def _apply_env_overrides(cfg: "Config") -> None:
    """Tune boot time vs throughput via env vars (see `make run` help)."""
    if os.environ.get("VLLM_PRODUCTION", "").lower() in ("1", "true", "yes"):
        cfg.optimization_level = 2
        cfg.max_batched_tokens = 32768
    elif level := os.environ.get("VLLM_OPTIMIZATION_LEVEL"):
        cfg.optimization_level = int(level)
    if os.environ.get("VLLM_FAST_BOOT", "").lower() in ("1", "true", "yes"):
        cfg.optimization_level = 0
        cfg.max_cudagraph_capture_size = min(cfg.max_cudagraph_capture_size, cfg.max_num_seqs)
        cfg.max_batched_tokens = min(cfg.max_batched_tokens, 16384)
    if size := os.environ.get("VLLM_MAX_CUDAGRAPH_CAPTURE_SIZE"):
        cfg.max_cudagraph_capture_size = int(size)
    if tokens := os.environ.get("VLLM_MAX_BATCHED_TOKENS"):
        cfg.max_batched_tokens = int(tokens)
    if cache := os.environ.get("VLLM_COMPILE_CACHE_DIR"):
        cfg.compile_cache_dir = Path(cache).expanduser()
    if hostname := os.environ.get("CF_TUNNEL_HOSTNAME"):
        cfg.cf_tunnel_hostname = hostname
    if name := os.environ.get("CF_TUNNEL_NAME"):
        cfg.cf_tunnel_name = name
    if model_len := os.environ.get("VLLM_MAX_MODEL_LEN"):
        cfg.max_model_len = int(model_len)
    if kv_dtype := os.environ.get("VLLM_KV_CACHE_DTYPE"):
        cfg.kv_cache_dtype = kv_dtype
    if rope := os.environ.get("VLLM_ROPE_SCALING"):
        cfg.rope_scaling_enabled = rope.lower() not in ("0", "false", "no", "off")
    if native := os.environ.get("VLLM_NATIVE_CONTEXT_LEN"):
        cfg.native_context_len = int(native)


def _boot_time_hint(cfg: "Config") -> str:
    if cfg.optimization_level <= 0:
        return "~1-2 min first boot (O0, no CUDA graphs)"
    if cfg.optimization_level == 1:
        return "~3-5 min first boot (O1); restarts faster with compile cache"
    if cfg.max_cudagraph_capture_size <= cfg.max_num_seqs:
        return "~4-7 min first boot; restarts ~1-3 min with compile cache"
    return "~7-10 min first boot (full CUDA graph capture)"


def _should_remove_container(cfg: "Config") -> bool:
    return os.environ.get("VLLM_REMOVE_CONTAINER", "").lower() in (
        "1",
        "true",
        "yes",
    ) or os.environ.get("VLLM_FORCE_RESTART", "").lower() in ("1", "true", "yes")


def _speculative_config_json(cfg: "Config") -> str:
    return json.dumps(
        {
            "method": "dflash",
            "model": "/models/drafter",
            "num_speculative_tokens": cfg.dflash_num_spec_tokens,
        },
        sort_keys=True,
    )


def _vllm_launch_fingerprint(cfg: "Config") -> str:
    payload = json.dumps(
        {
            "image": cfg.vllm_image,
            "model": str(_model_path(cfg)),
            "drafter": str(_drafter_path(cfg)),
            "optimization_level": cfg.optimization_level,
            "gpu_mem_util": cfg.gpu_mem_util,
            "max_model_len": cfg.max_model_len,
            "max_num_seqs": cfg.max_num_seqs,
            "max_batched_tokens": cfg.max_batched_tokens,
            "max_cudagraph_capture_size": cfg.max_cudagraph_capture_size,
            "speculative": _speculative_config_json(cfg),
            "rope_scaling": _rope_scaling_json(cfg),
            "kv_cache_dtype": cfg.kv_cache_dtype,
            "native_context_len": _model_native_context(cfg),
            "port": cfg.vllm_port,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _compile_cache_populated(cfg: "Config") -> bool:
    if not cfg.compile_cache_dir.is_dir():
        return False
    for sub in ("torchinductor", "triton"):
        d = cfg.compile_cache_dir / sub
        if d.is_dir() and any(d.rglob("*")):
            return True
    compile_root = cfg.compile_cache_dir / "torch_compile_cache"
    return compile_root.is_dir() and any(compile_root.rglob("*"))


_COMPILE_CACHE_SUBDIRS = (
    "triton",
    "torchinductor",
    "torch_compile_cache",
    "dummy_cache",
)


def _prepare_compile_cache_dir(cfg: "Config", docker_cmd: Optional[list] = None) -> None:
    cfg.compile_cache_dir.mkdir(parents=True, exist_ok=True)
    probe = cfg.compile_cache_dir / ".write_probe"
    try:
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return
    except OSError:
        pass

    uid, gid = os.getuid(), os.getgid()
    warn(
        f"Compile cache not writable ({cfg.compile_cache_dir}) — "
        f"fixing ownership to {uid}:{gid}"
    )
    if docker_cmd:
        r = subprocess.run(
            [
                *docker_cmd,
                "run",
                "--rm",
                "-v",
                f"{cfg.compile_cache_dir}:/cache",
                "busybox",
                "chown",
                "-R",
                f"{uid}:{gid}",
                "/cache",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            ok(f"Compile cache ownership fixed ({cfg.compile_cache_dir})")
            return
        warn(f"Docker chown failed: {(r.stderr or r.stdout).strip()}")

    chown = subprocess.run(
        ["sudo", "chown", "-R", f"{uid}:{gid}", str(cfg.compile_cache_dir)],
        capture_output=True,
        text=True,
    )
    if chown.returncode != 0:
        die(
            f"Cannot write compile cache at {cfg.compile_cache_dir}.\n"
            f"  Fix manually: sudo chown -R {uid}:{gid} {cfg.compile_cache_dir}"
        )
    ok(f"Compile cache ownership fixed ({cfg.compile_cache_dir})")


def _clear_compile_cache(cfg: "Config") -> None:
    removed: list[str] = []
    for name in _COMPILE_CACHE_SUBDIRS:
        path = cfg.compile_cache_dir / name
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(name)
    if removed:
        ok(f"Cleared compile cache ({', '.join(removed)}) at {cfg.compile_cache_dir}")
    else:
        info(f"Compile cache already empty at {cfg.compile_cache_dir}")


def _repair_triton_cache(cfg: "Config") -> int:
    """Sync missing Triton cubins into TRITON_CACHE_DIR from inductor_cache."""
    cache = cfg.compile_cache_dir
    triton_root = cache / "triton"
    triton_root.mkdir(parents=True, exist_ok=True)

    for tmp in triton_root.glob("tmp.*"):
        if tmp.is_dir():
            shutil.rmtree(tmp, ignore_errors=True)

    compile_root = cache / "torch_compile_cache"
    if not compile_root.is_dir():
        return 0

    synced = 0
    seen: set[Path] = set()
    for cubin in compile_root.rglob("inductor_cache/triton/*/*.cubin"):
        hash_dir = cubin.parent
        if hash_dir in seen:
            continue
        seen.add(hash_dir)
        dest_dir = triton_root / hash_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in hash_dir.iterdir():
            if not src.is_file():
                continue
            target = dest_dir / src.name
            if target.exists():
                continue
            try:
                os.link(src, target)
            except OSError:
                shutil.copy2(src, target)
            synced += 1
    return synced


def _ensure_compile_cache(cfg: "Config", docker_cmd: Optional[list] = None) -> None:
    _prepare_compile_cache_dir(cfg, docker_cmd)
    if os.environ.get("VLLM_CLEAR_COMPILE_CACHE", "").lower() in ("1", "true", "yes"):
        section("Clearing compile cache")
        _clear_compile_cache(cfg)
        return
    if not _compile_cache_populated(cfg):
        return
    section("Checking compile cache")
    synced = _repair_triton_cache(cfg)
    if synced:
        ok(
            f"Repaired Triton cache: linked/copied {synced} missing artifact(s) "
            f"into {cfg.compile_cache_dir / 'triton'}"
        )
    else:
        ok("Compile cache looks consistent")


def _resolve_optimization_profile(cfg: "Config") -> None:
    """Pick optimization level after GPU preflight (env overrides win)."""
    fast_boot = os.environ.get("VLLM_FAST_BOOT", "").lower() in ("1", "true", "yes")
    explicit_production = os.environ.get("VLLM_PRODUCTION", "").lower() in (
        "1",
        "true",
        "yes",
    )
    explicit_level = os.environ.get("VLLM_OPTIMIZATION_LEVEL")

    if fast_boot:
        cfg.optimization_level = 0
        cfg.boot_profile = "fast boot (O0)"
    elif explicit_production:
        cfg.optimization_level = 2
        cfg.max_batched_tokens = 32768
        cfg.boot_profile = "production (O2, VLLM_PRODUCTION=1)"
    elif explicit_level:
        cfg.boot_profile = (
            f"explicit (O{cfg.optimization_level}, VLLM_OPTIMIZATION_LEVEL)"
        )
    elif _compile_cache_populated(cfg) and cfg.gpu_exclusive:
        cfg.optimization_level = 2
        cfg.max_batched_tokens = 32768
        cfg.boot_profile = "O2 (warm cache + exclusive GPU)"
    elif _compile_cache_populated(cfg):
        cfg.optimization_level = 1
        cfg.boot_profile = "O1 (warm cache, shared GPU budget)"
    else:
        cfg.optimization_level = 1
        cfg.boot_profile = "O1 (cold cache — building compile cache)"
    info(f"Auto profile: {cfg.boot_profile}")


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
    cf_tunnel_token: str = ""
    hf_token: str = ""

    # Cloudflare tunnel — connector token fetched via CLOUDFLARE_API_TOKEN at runtime
    cf_tunnel_name: str = "spark-serve"
    cf_tunnel_hostname: str = "vllm.chrisvouga.dev"

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
    max_model_len: int = 262144  # 256K + YaRN for long agentic-coding sessions
    kv_cache_dtype: str = "fp8"
    rope_scaling_enabled: bool = True
    native_context_len: int = 0  # 0 = auto-detect from model config.json
    gpu_mem_util: float = 0.85
    max_num_seqs: int = 16  # hard ceiling on GB10
    max_batched_tokens: int = 16384
    dflash_num_spec_tokens: int = 15  # k=15 optimal for code (~78% acceptance)
    # vLLM defaults capture CUDA graphs up to 512 batch slots; we only run 16 seqs.
    max_cudagraph_capture_size: int = 16
    # 0=eager (~1-2 min), 1=balanced (default), 2=production. VLLM_PRODUCTION=1 for O2.
    optimization_level: int = 1
    container_name: str = "vllm-qwen36-dflash"
    vllm_image: str = "ghcr.io/aeon-7/vllm-spark-omni-q36:v1.2"
    compile_cache_dir: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "vllm-spark-compile"
    )
    docker_cmd: list = field(default_factory=lambda: ["docker"])
    gpu_exclusive: bool = True
    boot_profile: str = ""

    # Runtime
    helper_dir: Path = field(default_factory=lambda: Path.home() / ".spark-serve")


# ── Process registry ──────────────────────────────────────────────────────────
_managed: list = []
_managed_containers: list = []
_shutdown_requested = False
_cleanup_done = False
_runtime_active = False


def register(proc):
    global _runtime_active
    _runtime_active = True
    _managed.append(proc)
    return proc


def register_container(name):
    global _runtime_active
    _runtime_active = True
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


def _kill_pid(pid: int, label: str, timeout: float = 5) -> None:
    try:
        os.kill(pid, 0)
    except OSError:
        return
    info(f"Stopping {label} (PID {pid})...")
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _stop_spark_tunnel(cfg):
    """Stop the vLLM tunnel started by this server (never touches lm-studio)."""
    pid_file = cfg.helper_dir / "cloudflared.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            _kill_pid(pid, "Cloudflare tunnel")
        except (OSError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)

    for proc in list(_managed):
        if proc.poll() is not None:
            continue
        try:
            with open(f"/proc/{proc.pid}/cmdline", "rb") as fh:
                if b"cloudflared" in fh.read():
                    _kill_pid(proc.pid, "Cloudflare tunnel")
        except OSError:
            pass


def cleanup(cfg):
    global _cleanup_done, _runtime_active
    if _cleanup_done:
        return
    _cleanup_done = True
    print(f"\n{B}━━━  Shutting down  ━━━{X}", flush=True)
    _stop_spark_tunnel(cfg)
    for proc in _managed:
        if proc.poll() is None:
            _kill_pid(proc.pid, f"process {proc.pid}")
    for name in _managed_containers:
        info(f"Stopping container '{name}'...")
        subprocess.run(
            [*cfg.docker_cmd, "stop", name], capture_output=True, timeout=30
        )
        if _should_remove_container(cfg):
            subprocess.run(
                [*cfg.docker_cmd, "rm", name], capture_output=True, timeout=30
            )
    (cfg.helper_dir / "server.pid").unlink(missing_ok=True)
    _runtime_active = False
    ok("Clean shutdown complete (vLLM + tunnel stopped).")


# ── Doppler ───────────────────────────────────────────────────────────────────
def _apply_doppler_secrets(cfg, secrets: dict, source: str) -> None:
    def require(key):
        val = secrets.get(key, "")
        if not val:
            die(
                f"Secret '{key}' not found in Doppler {cfg.doppler_project}/{cfg.doppler_config}"
            )
        return val

    cfg.cf_api_token = secrets.get("CLOUDFLARE_API_TOKEN", "").strip()
    cfg.cf_account_id = secrets.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    cfg.cf_tunnel_token = (
        secrets.get("CF_TUNNEL_TOKEN", "")
        or secrets.get("CLOUDFLARE_TUNNEL_TOKEN", "")
    ).strip()
    cfg.hf_token = secrets.get("HF_TOKEN", "")

    ok(f"Secrets loaded from {source} ({cfg.doppler_project}/{cfg.doppler_config})")
    if not cfg.cf_api_token:
        die(
            f"Missing CLOUDFLARE_API_TOKEN in Doppler ({cfg.doppler_project}/{cfg.doppler_config}).\n"
            "  Token needs Account → Cloudflare Tunnel → Edit."
        )
    if not cfg.cf_account_id:
        die(
            f"Missing CLOUDFLARE_ACCOUNT_ID in Doppler ({cfg.doppler_project}/{cfg.doppler_config})."
        )
    ok("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID loaded")
    if cfg.cf_tunnel_token:
        warn("Using CF_TUNNEL_TOKEN override instead of fetching connector token via API")
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
class CloudflareAPIError(Exception):
    def __init__(self, code: int, message: str, body: str = ""):
        self.code = code
        self.message = message
        self.body = body
        super().__init__(f"HTTP {code}: {message}")


def _http_request(method: str, url: str, headers=None, data=None, timeout: int = 10):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        message = raw
        try:
            payload = json.loads(raw)
            errors = payload.get("errors") or []
            if errors:
                message = errors[0].get("message", raw)
        except json.JSONDecodeError:
            pass
        raise CloudflareAPIError(e.code, message, raw) from e
    except urllib.error.URLError as e:
        die(f"HTTP request failed for {url}: {e.reason}")


def http_get(url, headers=None):
    return _http_request("GET", url, headers=headers)


def http_post(url, data, headers=None):
    return _http_request("POST", url, headers=headers, data=data)


def http_put(url, data, headers=None):
    return _http_request("PUT", url, headers=headers, data=data)


def cf_headers(cfg):
    return {
        "Authorization": f"Bearer {cfg.cf_api_token}",
        "Content-Type": "application/json",
    }


def _cf_tunnel_api_base(cfg) -> str:
    return (
        f"https://api.cloudflare.com/client/v4/accounts/{cfg.cf_account_id}/cfd_tunnel"
    )


def _cf_api_token_help(cfg) -> str:
    return (
        f"Grant CLOUDFLARE_API_TOKEN Account → Cloudflare Tunnel → Edit "
        f"({cfg.doppler_project}/{cfg.doppler_config})."
    )


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


# ── Cloudflare tunnel ─────────────────────────────────────────────────────────
def precheck_cf_tunnel(cfg):
    section("Precheck: Cloudflare tunnel")
    if not shutil.which("cloudflared"):
        die("cloudflared not found — install it or run: make ensure-system-deps")

    if cfg.cf_tunnel_token and len(cfg.cf_tunnel_token) < 40:
        die(
            "CF_TUNNEL_TOKEN looks too short — copy the full Docker connector token "
            "from the Cloudflare Zero Trust dashboard."
        )

    if not cfg.cf_api_token or not cfg.cf_account_id:
        die(
            "Cloudflare API credentials missing from Doppler.\n"
            + _cf_api_token_help(cfg)
        )

    info(f"Checking API access for tunnel '{cfg.cf_tunnel_name}'...")
    try:
        resp = http_get(
            f"{_cf_tunnel_api_base(cfg)}?name={cfg.cf_tunnel_name}&is_deleted=false",
            cf_headers(cfg),
        )
    except CloudflareAPIError as e:
        die(
            "Cloudflare tunnel precheck failed — refusing to start vLLM.\n\n"
            f"  API error: HTTP {e.code}: {e.message}\n\n"
            "  Your CLOUDFLARE_API_TOKEN is valid but lacks tunnel permissions.\n"
            f"  Fix: {_cf_api_token_help(cfg)}"
        )

    if not resp.get("success", True):
        die(f"Cloudflare API returned success=false: {resp}")
    ok("Cloudflare API can list tunnels")


def _cf_public_url(cfg) -> str:
    return f"https://{cfg.cf_tunnel_hostname}"


def _cf_service_url(cfg) -> str:
    return f"http://127.0.0.1:{cfg.vllm_port}"


def merge_tunnel_ingress(
    existing: list[dict], hostname: str, service: str
) -> list[dict]:
    """Merge a public hostname route into tunnel ingress (catch-all last)."""
    merged: list[dict] = []
    replaced = False
    for rule in existing:
        svc = rule.get("service", "")
        if rule.get("hostname") == hostname:
            merged.append(
                {"hostname": hostname, "service": service, "originRequest": {}}
            )
            replaced = True
        elif "http_status" in str(svc):
            continue
        else:
            merged.append(rule)
    if not replaced:
        merged.append(
            {"hostname": hostname, "service": service, "originRequest": {}}
        )
    merged.append({"service": "http_status:404"})
    return merged


def _cf_zone_id_for_hostname(cfg, hostname: str, hdrs: dict) -> str:
    zone_name = hostname.split(".", 1)[1]
    resp = http_get(
        f"https://api.cloudflare.com/client/v4/zones?name={zone_name}", hdrs
    )
    zones = resp.get("result", [])
    if not zones:
        die(f"Cloudflare zone not found for hostname '{hostname}' (zone: {zone_name})")
    return zones[0]["id"]


def _cf_ensure_tunnel_dns(cfg, tunnel_id: str, hdrs: dict) -> None:
    hostname = cfg.cf_tunnel_hostname
    zone_id = _cf_zone_id_for_hostname(cfg, hostname, hdrs)
    record_name = hostname.split(".", 1)[0]
    content = f"{tunnel_id}.cfargotunnel.com"

    resp = http_get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        f"?type=CNAME&name={hostname}",
        hdrs,
    )
    records = resp.get("result", [])
    if records:
        rec = records[0]
        if rec.get("content") == content and rec.get("proxied"):
            ok(f"DNS already routed: {hostname} → {content}")
            return
        http_put(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{rec['id']}",
            {
                "type": "CNAME",
                "name": record_name,
                "content": content,
                "proxied": True,
            },
            hdrs,
        )
    else:
        http_post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            {
                "type": "CNAME",
                "name": record_name,
                "content": content,
                "proxied": True,
            },
            hdrs,
        )
    ok(f"DNS routed: {hostname} → {content}")


def _ingress_already_routed(
    existing: list[dict], hostname: str, service: str
) -> bool:
    for rule in existing:
        if rule.get("hostname") == hostname and rule.get("service") == service:
            return True
    return False


def _tunnel_ingress_from_config_response(resp: dict) -> list[dict]:
    """Parse ingress rules from GET /cfd_tunnel/{id}/configurations."""
    result = resp.get("result") or {}
    config = result.get("config") or {}
    return config.get("ingress", []) or []


def _cf_ensure_tunnel_ingress(cfg, tunnel_id: str, hdrs: dict) -> None:
    base = _cf_tunnel_api_base(cfg)
    service = _cf_service_url(cfg)
    hostname = cfg.cf_tunnel_hostname

    existing: list[dict] = []
    try:
        resp = http_get(f"{base}/{tunnel_id}/configurations", hdrs)
        existing = _tunnel_ingress_from_config_response(resp)
    except CloudflareAPIError as e:
        if e.code != 404:
            raise

    if _ingress_already_routed(existing, hostname, service):
        ok(f"Tunnel ingress already set: {hostname} → {service}")
        return

    ingress = merge_tunnel_ingress(existing, hostname, service)
    http_put(
        f"{base}/{tunnel_id}/configurations",
        {"config": {"ingress": ingress}},
        hdrs,
    )
    ok(f"Tunnel ingress: {hostname} → {service}")


def _cf_get_or_create_tunnel_id(cfg, hdrs: dict) -> str:
    base = _cf_tunnel_api_base(cfg)
    resp = http_get(f"{base}?name={cfg.cf_tunnel_name}&is_deleted=false", hdrs)
    tunnels = resp.get("result", [])
    if tunnels:
        tunnel_id = tunnels[0]["id"]
        ok(f"Reusing tunnel '{cfg.cf_tunnel_name}' ({tunnel_id})")
        return tunnel_id

    info(f"Creating tunnel '{cfg.cf_tunnel_name}'...")
    resp = http_post(
        base,
        {
            "name": cfg.cf_tunnel_name,
            "tunnel_secret": os.urandom(32).hex(),
            "config_src": "cloudflare",
        },
        hdrs,
    )
    tunnel_id = resp["result"]["id"]
    ok(f"Created tunnel '{cfg.cf_tunnel_name}' ({tunnel_id})")
    return tunnel_id


def resolve_cf_tunnel_token(cfg) -> str:
    """Return connector token; ensure DNS + ingress for cfg.cf_tunnel_hostname."""
    section("Resolving Cloudflare tunnel token (API)")
    base = _cf_tunnel_api_base(cfg)
    hdrs = cf_headers(cfg)

    try:
        tunnel_id = _cf_get_or_create_tunnel_id(cfg, hdrs)
        section(f"Routing tunnel to {_cf_public_url(cfg)}")
        _cf_ensure_tunnel_ingress(cfg, tunnel_id, hdrs)
        _cf_ensure_tunnel_dns(cfg, tunnel_id, hdrs)

        if cfg.cf_tunnel_token:
            ok("Using connector token from secrets (routes updated via API)")
            return cfg.cf_tunnel_token

        tok = http_get(f"{base}/{tunnel_id}/token", hdrs)
        return tok["result"]
    except CloudflareAPIError as e:
        die(
            f"Could not configure Cloudflare tunnel via API: HTTP {e.code}: {e.message}\n"
            + _cf_api_token_help(cfg)
            + "\n  DNS setup also needs Zone → DNS → Edit on the API token."
        )


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


_DEFAULT_NATIVE_CONTEXT = 32768


def _model_native_context(cfg: "Config") -> int:
    if cfg.native_context_len > 0:
        return cfg.native_context_len
    config_path = _model_path(cfg) / "config.json"
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                data = json.load(fh)
            native = data.get("max_position_embeddings")
            if isinstance(native, int) and native > 0:
                return native
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return _DEFAULT_NATIVE_CONTEXT


def _rope_scaling_json(cfg: "Config") -> str:
    if not cfg.rope_scaling_enabled:
        return ""
    native = _model_native_context(cfg)
    if cfg.max_model_len <= native:
        return ""
    factor = math.ceil(cfg.max_model_len / native)
    return json.dumps(
        {
            "rope_type": "yarn",
            "factor": factor,
            "original_max_position_embeddings": native,
        },
        sort_keys=True,
    )


def _drafter_path(cfg):
    return cfg.model_dir / "drafter"


def _model_cached(path: Path) -> bool:
    return path.exists() and any(path.glob("*.safetensors"))


def precheck_models(cfg):
    section("Precheck: models")
    _ensure_model_dir(cfg)
    info(f"Model dir: {cfg.model_dir}")

    missing = []
    if not _model_cached(_model_path(cfg)):
        missing.append(f"  • {cfg.model} → {_model_path(cfg)}")
    if not _model_cached(_drafter_path(cfg)):
        missing.append(f"  • {cfg.dflash_drafter} → {_drafter_path(cfg)}")

    if missing:
        warn("Models not cached yet — will download after prechecks:")
        for line in missing:
            warn(line)
    else:
        ok(f"Models cached at {cfg.model_dir}")


def precheck_gpu_available(cfg, docker_cmd):
    section("Precheck: GPU")
    if shutil.which("nvidia-smi"):
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True)
        if r.returncode == 0:
            ok(r.stdout.strip().splitlines()[0])
        else:
            warn("nvidia-smi failed — continuing, Docker GPU test is authoritative")
    mem = _probe_gpu(docker_cmd, cfg.vllm_image)
    if mem is None and not _gpu_test(docker_cmd):
        die(
            "GPU not available inside Docker.\n"
            "  Check: nvidia-smi\n"
            "  Install: NVIDIA container toolkit"
        )
    ok("Docker GPU access OK")


def run_prechecks(cfg, docker_cmd):
    """Validate config and dependencies before the slow vLLM boot."""
    section("Running prechecks (fail fast)")
    precheck_cf_tunnel(cfg)
    precheck_gpu_available(cfg, docker_cmd)
    precheck_models(cfg)
    _check_gpu_memory(cfg, docker_cmd)
    ok("All prechecks passed — starting vLLM")


def ensure_models(cfg, docker_cmd):
    section("Checking models")
    info(f"Model dir: {cfg.model_dir}")
    _ensure_model_dir(cfg)

    def download_if_missing(repo, local_dir, size_hint):
        if _model_cached(local_dir):
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
def _image_exists_locally(docker_cmd, image: str) -> bool:
    return (
        subprocess.run(
            [*docker_cmd, "image", "inspect", image],
            capture_output=True,
        ).returncode
        == 0
    )


def pull_vllm_image(cfg, docker_cmd):
    section("Pulling vLLM image")
    force_pull = os.environ.get("VLLM_PULL", "").lower() in (
        "always",
        "1",
        "true",
        "yes",
    )
    if not force_pull and _image_exists_locally(docker_cmd, cfg.vllm_image):
        ok(f"Image cached locally: {cfg.vllm_image}")
        return

    info(f"Image: {cfg.vllm_image}  (~9 GB on first pull)")
    try:
        run([*docker_cmd, "pull", cfg.vllm_image])
        ok("Image ready")
    except subprocess.CalledProcessError:
        if _image_exists_locally(docker_cmd, cfg.vllm_image):
            warn("Pull failed — using local image")
            ok(f"Image cached locally: {cfg.vllm_image}")
        else:
            raise


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


def _check_gpu_memory(cfg, docker_cmd):
    section("Checking GPU memory")
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


def start_vllm(cfg, docker_cmd) -> str:
    """Start or reuse the vLLM container (see return values in main())."""
    section("Starting vLLM + DFlash  [Qwen3.6-35B-A3B NVFP4, k=15]")
    info("Target: 120-150 tok/s on coding workloads via DFlash speculative decoding")
    info(f"Boot estimate: {_boot_time_hint(cfg)} (O{cfg.optimization_level})")
    _prepare_compile_cache_dir(cfg, docker_cmd)
    if _compile_cache_populated(cfg):
        info(f"Reusing compile cache at {cfg.compile_cache_dir}")
    else:
        info(f"Saving compile cache to {cfg.compile_cache_dir} (speeds up future restarts)")

    force_restart = _should_remove_container(cfg)
    status = _container_status(cfg)
    fingerprint = _vllm_launch_fingerprint(cfg)

    if not force_restart and status == "running":
        register_container(cfg.container_name)
        if _vllm_ready(cfg):
            ok(f"Container '{cfg.container_name}' already healthy — skipping restart")
            return "ready"
        info(
            f"Container '{cfg.container_name}' is still booting — "
            "waiting without restart (preserves compile progress)"
        )
        return "booting"

    if not force_restart and status == "exited":
        if _container_config_hash(cfg) == fingerprint:
            info(f"Restarting stopped container '{cfg.container_name}' (docker start)...")
            run([*docker_cmd, "start", cfg.container_name])
            register_container(cfg.container_name)
            ok(f"Container '{cfg.container_name}' started")
            return "started"
        warn("Container config changed — recreating")
        remove_container(cfg, docker_cmd)
    elif status not in ("missing",):
        remove_container(cfg, docker_cmd)

    register_container(cfg.container_name)
    spec_config = _speculative_config_json(cfg)
    rope_config = _rope_scaling_json(cfg)
    native_ctx = _model_native_context(cfg)
    if rope_config:
        info(
            f"Context window: {cfg.max_model_len} tokens "
            f"(YaRN {json.loads(rope_config)['factor']}x over native {native_ctx})"
        )
    else:
        info(f"Context window: {cfg.max_model_len} tokens (native {native_ctx})")

    vllm_serve_args = [
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
            "--kv-cache-dtype",
            str(cfg.kv_cache_dtype),
            "--max-num-seqs",
            str(cfg.max_num_seqs),
            "--max-num-batched-tokens",
            str(cfg.max_batched_tokens),
            "--max-cudagraph-capture-size",
            str(cfg.max_cudagraph_capture_size),
            "--optimization-level",
            str(cfg.optimization_level),
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
    if rope_config:
        vllm_serve_args.extend(["--rope-scaling", rope_config])

    run(
        [
            *docker_cmd,
            "run",
            "-d",
            "--name",
            cfg.container_name,
            "--label",
            f"{_CONFIG_HASH_LABEL}={fingerprint}",
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
            "-v",
            str(cfg.compile_cache_dir) + ":/root/.cache/vllm",
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
            "TORCHINDUCTOR_CACHE_DIR=/root/.cache/vllm/torchinductor",
            "-e",
            "TRITON_CACHE_DIR=/root/.cache/vllm/triton",
            "-e",
            "HF_TOKEN=" + cfg.hf_token,
            "-e",
            "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
            cfg.vllm_image,
            # Match AEON-7 docker-compose.yml — NVFP4 needs compressed-tensors
            *vllm_serve_args,
        ]
    )
    ok(f"Container '{cfg.container_name}' started")
    return "started"


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


def _health_max_wait(cfg) -> int:
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
            "Stop it and run `make kill && make run` again.\n"
        )
    return ""


def wait_for_vllm(cfg):
    section("Waiting for vLLM to be ready")
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

        if _vllm_ready(cfg):
            ok(f"vLLM ready after {elapsed}s (health + {_SERVED_MODEL})")
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
        f"vLLM not ready after {max_wait}s.\n"
        f"Container status: {_container_status(cfg)}\n"
        f"Recent logs:\n{_container_logs_tail(cfg)}"
    )


def warmup_vllm(cfg):
    if cfg.optimization_level <= 0:
        ok("Warmup skipped (O0 / eager mode)")
        return
    if os.environ.get("VLLM_SKIP_WARMUP", "").lower() in ("1", "true", "yes"):
        ok("Warmup skipped (VLLM_SKIP_WARMUP)")
        return
    if _compile_cache_populated(cfg) and cfg.optimization_level <= 1:
        ok("Warmup skipped (compile cache present)")
        return
    runs = 1 if cfg.optimization_level == 1 else 2
    info(
        f"Warming up ({runs} coding-shaped request(s) for CUDA graph specialisation)..."
    )
    url = f"http://localhost:{cfg.vllm_port}/v1/completions"
    payload = json.dumps(
        {
            "model": _SERVED_MODEL,
            "prompt": _WARMUP_PROMPT,
            "max_tokens": 64,
        }
    ).encode()
    for _ in range(runs):
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
    info(f"Tunnel managed by this process — stops on Ctrl+C / make kill ({cfg.cf_tunnel_hostname})")

    info("Waiting for tunnel to connect...")
    time.sleep(6)

    if proc.poll() is not None:
        die(f"cloudflared exited.\nLog:\n{cf_log.read_text()[-1000:]}")

    ok(f"Cloudflare tunnel running (PID {proc.pid})")

    return _cf_public_url(cfg)


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
    root = Path(__file__).resolve().parent.parent
    (d / "stop.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"exec python3 \"{root}/server/server.py\" --stop\n"
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
        f"curl -sf {_cf_public_url(cfg)}/health >/dev/null 2>&1 "
        f'&& echo -e "${{G}}● public: {_cf_public_url(cfg)}${{X}}" '
        f'|| echo -e "${{Y}}! public: {_cf_public_url(cfg)} (not reachable yet)${{X}}"\n'
    )
    for f in d.glob("*.sh"):
        f.chmod(0o755)
    ok(f"Helpers written to {d}/")


# ── Summary ───────────────────────────────────────────────────────────────────
def _context_summary(cfg) -> str:
    rope = _rope_scaling_json(cfg)
    if rope:
        native = _model_native_context(cfg)
        factor = json.loads(rope)["factor"]
        return (
            f"{cfg.max_model_len} tokens (YaRN {factor}x over {native}, "
            f"KV {cfg.kv_cache_dtype})"
        )
    return f"{cfg.max_model_len} tokens (KV {cfg.kv_cache_dtype})"


def print_summary(cfg, cf_url):
    section("🚀 Server is live")
    d = cfg.helper_dir
    print(
        f"""
  {B}Model:{X}    {cfg.model}
  {B}DFlash:{X}   {cfg.dflash_drafter} (k={cfg.dflash_num_spec_tokens})
  {B}Profile:{X}  O{cfg.optimization_level} — {cfg.boot_profile or "default"}
  {B}GPU budget:{X} {cfg.gpu_mem_util:.0%}  |  compile cache: {"warm" if _compile_cache_populated(cfg) else "cold"}
  {B}Target:{X}   120-150 tok/s on coding  |  300+ tok/s aggregate at concurrency 16
  {B}Context:{X}  {_context_summary(cfg)}  |  {B}Max seqs:{X} {cfg.max_num_seqs}
 
  {B}Local API:{X}
    http://localhost:{cfg.vllm_port}/v1
 
  {B}Public API (Cloudflare):{X}
    {G}{_cf_public_url(cfg)}/v1{X}
 
  {B}Agent config (local):{X}
    base_url  = http://localhost:{cfg.vllm_port}/v1
    api_key   = not-required
    model     = qwen3.6-35b
 
  {B}Agent config (public):{X}
    base_url  = {_cf_public_url(cfg)}/v1
    api_key   = not-required
    model     = qwen3.6-35b
 
  {B}Commands:{X}
    {d}/status.sh
    {d}/logs.sh
    {d}/stop.sh
    docker logs -f {cfg.container_name}
"""
    )
    warn("Keep this process running — Ctrl+C or `make kill` stops vLLM + tunnel.")
    warn("First novel request shape takes ~30s for CUDA graph specialisation.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
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
        run_prechecks(cfg, docker_cmd)
        _exit_on_shutdown(cfg)

        _ensure_compile_cache(cfg, docker_cmd)
        _exit_on_shutdown(cfg)
        _resolve_optimization_profile(cfg)

        pull_vllm_image(cfg, docker_cmd)
        _exit_on_shutdown(cfg)
        ensure_models(cfg, docker_cmd)
        boot_mode = start_vllm(cfg, docker_cmd)
        if boot_mode != "ready":
            wait_for_vllm(cfg)
            warmup_vllm(cfg)
        _exit_on_shutdown(cfg)

        tunnel_token = resolve_cf_tunnel_token(cfg)
        _exit_on_shutdown(cfg)
        cf_url = start_cf_tunnel(cfg, tunnel_token)

        write_helpers(cfg)
        (cfg.helper_dir / "server.pid").write_text(str(os.getpid()))
        print_summary(cfg, cf_url)

        info("Running. Press Ctrl+C or `make kill` to stop vLLM + tunnel.")
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
                logs = _container_logs_tail(cfg, lines=80)
                oom_hint = _gpu_oom_hint(logs)
                if oom_hint:
                    die(
                        f"Container '{cfg.container_name}' exited (likely GPU memory)."
                        f"{oom_hint}\nRecent logs:\n{logs}"
                    )
                warn("Container exited unexpectedly — restarting...")
                boot_mode = start_vllm(cfg, docker_cmd)
                if boot_mode != "ready":
                    wait_for_vllm(cfg)
                    warmup_vllm(cfg)
            if not _sleep(30):
                break

    except KeyboardInterrupt:
        _request_shutdown()
    except SystemExit:
        raise
    except CloudflareAPIError as e:
        err(f"Cloudflare API error: HTTP {e.code}: {e.message}")
        if e.body:
            err(e.body[:500])
        raise SystemExit(1) from e
    except Exception as e:
        err(f"Unexpected error: {e}")
        cleanup(cfg)
        # If vLLM survived cleanup stop failure, say so.
        if _container_status(cfg) == "running":
            warn("vLLM container may still be running — run: make kill")
        raise
    finally:
        if _shutdown_requested or _runtime_active:
            cleanup(cfg)


def stop_managed():
    """Stop vLLM container + Cloudflare tunnel started by make run."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    cfg.docker_cmd = _resolve_docker_cmd() or ["docker"]
    register_container(cfg.container_name)
    cleanup(cfg)


def setup_tunnel_only():
    """Configure DNS + ingress for vLLM without starting the server."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    fetch_doppler_secrets(cfg)
    ensure_cloudflared()
    precheck_cf_tunnel(cfg)
    resolve_cf_tunnel_token(cfg)
    ok(f"Public API will be at {_cf_public_url(cfg)}/v1 (start with: make run)")


def clear_compile_cache_only():
    """Remove vLLM torch/Triton compile artifacts (forces a cold recompile)."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    cfg.docker_cmd = _resolve_docker_cmd() or ["docker"]
    section("Clearing compile cache")
    _prepare_compile_cache_dir(cfg, cfg.docker_cmd)
    _clear_compile_cache(cfg)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--setup-tunnel", "setup-tunnel"):
        setup_tunnel_only()
    elif len(sys.argv) > 1 and sys.argv[1] in ("--stop", "stop"):
        stop_managed()
    elif len(sys.argv) > 1 and sys.argv[1] in (
        "--clear-compile-cache",
        "clear-compile-cache",
    ):
        clear_compile_cache_only()
    else:
        main()
