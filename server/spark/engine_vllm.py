"""vLLM engine: image pull + container launch for GB10/DGX Spark."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .config import _CONFIG_HASH_LABEL, _should_remove_container
from .console import info, ok, section, warn
from .containers import (
    _container_config_hash,
    _container_exit_code,
    _container_restart_count,
    _container_status,
    _image_exists_locally,
    remove_container,
)
from .gpu import _gpu_run_flags
from .health import _engine_ready
from .runtime import register_container
from .shell import run


def _hf_repo_cached(model_id: str) -> bool:
    """True if model weights are present in the host HF hub cache."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = hub / ("models--" + model_id.replace("/", "--"))
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return False
    return any(snapshots.rglob("*.safetensors")) or any(
        snapshots.rglob("*.bin")
    )


def _download_hf_model(cfg, docker_cmd, model_id: str, size_hint: str) -> None:
    hf_cache = Path.home() / ".cache" / "huggingface"
    hf_cache.mkdir(parents=True, exist_ok=True)
    info(f"Downloading {model_id} into HF cache  ({size_hint})")
    py_cmd = (
        "from huggingface_hub import snapshot_download; "
        "snapshot_download('" + model_id + "')"
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
            f"{hf_cache}:/root/.cache/huggingface",
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
    ok(f"Downloaded: {model_id}")


def ensure_vllm_model(cfg, docker_cmd):
    """Pre-download target + DFlash drafter into the mounted HF hub cache."""
    section("Checking vLLM models")
    if _hf_repo_cached(cfg.vllm_model):
        ok(f"Target model cached: {cfg.vllm_model}")
    else:
        _download_hf_model(cfg, docker_cmd, cfg.vllm_model, "~43 GB NVFP4")

    if not cfg.vllm_speculative or not cfg.vllm_dflash_model:
        return

    if _hf_repo_cached(cfg.vllm_dflash_model):
        ok(f"DFlash drafter cached: {cfg.vllm_dflash_model}")
    else:
        _download_hf_model(
            cfg, docker_cmd, cfg.vllm_dflash_model, "~900 MB DFlash drafter"
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

    info(f"Image: {cfg.vllm_image}  (large on first pull)")
    try:
        run([*docker_cmd, "pull", cfg.vllm_image])
        ok("Image ready")
    except subprocess.CalledProcessError:
        if _image_exists_locally(docker_cmd, cfg.vllm_image):
            warn("Pull failed — using local image")
            ok(f"Image cached locally: {cfg.vllm_image}")
        else:
            raise


def _vllm_speculative_config(cfg) -> str | None:
    if not cfg.vllm_speculative or not cfg.vllm_dflash_model:
        return None
    payload = {
        "method": "dflash",
        "model": cfg.vllm_dflash_model,
        "num_speculative_tokens": cfg.vllm_dflash_tokens,
    }
    return json.dumps(payload, separators=(",", ":"))


def _vllm_serve_args(cfg) -> list:
    args = [
        "serve",
        cfg.vllm_model,
        "--host",
        "0.0.0.0",
        "--port",
        str(cfg.vllm_port),
        "--served-model-name",
        cfg.vllm_served_model_name,
        "--max-model-len",
        str(cfg.vllm_max_model_len),
        "--gpu-memory-utilization",
        str(cfg.vllm_gpu_mem_util),
        "--kv-cache-dtype",
        str(cfg.vllm_kv_cache_dtype),
        "--attention-backend",
        str(cfg.vllm_attention_backend),
        "--load-format",
        str(cfg.vllm_load_format),
        "--moe-backend",
        str(cfg.vllm_moe_backend),
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "qwen3_coder",
        "--enable-prefix-caching",
        "--trust-remote-code",
    ]
    if spec := _vllm_speculative_config(cfg):
        args.extend(["--speculative-config", spec])
    if cfg.vllm_enforce_eager:
        args.append("--enforce-eager")
    return args


def _vllm_launch_fingerprint(cfg) -> str:
    payload = json.dumps(
        {
            "image": cfg.vllm_image,
            "model": cfg.vllm_model,
            "dflash": cfg.vllm_dflash_model if cfg.vllm_speculative else None,
            "port": cfg.vllm_port,
            "serve": _vllm_serve_args(cfg),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def start_vllm(cfg, docker_cmd) -> str:
    """Start or reuse the vLLM container."""
    spec = (
        f"DFlash ({cfg.vllm_dflash_model})"
        if cfg.vllm_speculative and cfg.vllm_dflash_model
        else "no speculative"
    )
    section(f"Starting vLLM  [{cfg.vllm_model}, {spec}]")
    info(
        f"Context: {cfg.vllm_max_model_len} tokens  |  "
        f"KV: {cfg.vllm_kv_cache_dtype}  |  GPU budget: {cfg.vllm_gpu_mem_util:.0%}"
    )
    info("vLLM cold-starts in ~1-2 min; first request may warm CUDA graphs")

    force_restart = _should_remove_container(cfg)
    status = _container_status(cfg)
    fingerprint = _vllm_launch_fingerprint(cfg)

    if not force_restart and status == "running":
        if _engine_ready(cfg):
            register_container(cfg.container_name)
            ok(f"Container '{cfg.container_name}' already healthy — skipping restart")
            return "ready"
        if _container_config_hash(cfg) != fingerprint:
            warn("Running container has stale config — recreating")
            remove_container(cfg, docker_cmd)
        elif _container_restart_count(cfg) >= 2:
            warn(
                f"Running container '{cfg.container_name}' is crash-looping "
                f"(restarts={_container_restart_count(cfg)}) — recreating"
            )
            remove_container(cfg, docker_cmd)
        else:
            register_container(cfg.container_name)
            info(f"Container '{cfg.container_name}' is still booting — waiting")
            return "booting"

    if not force_restart and status == "exited":
        exit_code = _container_exit_code(cfg)
        if _container_config_hash(cfg) == fingerprint and exit_code == 0:
            info(f"Restarting stopped container '{cfg.container_name}' (docker start)...")
            run([*docker_cmd, "start", cfg.container_name])
            register_container(cfg.container_name)
            ok(f"Container '{cfg.container_name}' started")
            return "started"
        if exit_code not in (None, 0):
            warn(
                f"Container '{cfg.container_name}' exited with code {exit_code} — recreating"
            )
        else:
            warn("Container config changed — recreating")
        remove_container(cfg, docker_cmd)
    elif status not in ("missing",):
        remove_container(cfg, docker_cmd)

    register_container(cfg.container_name)
    hf_cache = Path.home() / ".cache" / "huggingface"
    hf_cache.mkdir(parents=True, exist_ok=True)

    docker_run = [
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
        "no",
        "-v",
        f"{hf_cache}:/root/.cache/huggingface",
        "-e",
        "HF_TOKEN=" + cfg.hf_token,
        "-e",
        "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
    ]
    for key, value in cfg.vllm_extra_env.items():
        docker_run.extend(["-e", f"{key}={value}"])
    docker_run.extend([cfg.vllm_image, *_vllm_serve_args(cfg)])

    run(docker_run)
    ok(f"Container '{cfg.container_name}' started")
    return "started"
