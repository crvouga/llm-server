"""Atlas engine: image pull + container launch."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .config import _CONFIG_HASH_LABEL, _should_remove_container
from .console import info, ok, section, warn
from .containers import (
    _container_config_hash,
    _container_restart_count,
    _container_status,
    _image_exists_locally,
    remove_container,
)
from .gpu import _gpu_run_flags
from .health import _atlas_ready
from .runtime import register_container
from .shell import run


def _atlas_model_cached(cfg) -> bool:
    """True if the Atlas model is already in the host HF hub cache."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = hub / ("models--" + cfg.atlas_model.replace("/", "--"))
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return False
    return any(snapshots.rglob("*.safetensors"))


def ensure_atlas_model(cfg, docker_cmd):
    """Atlas needs the checkpoint pre-downloaded into the mounted HF hub cache."""
    section("Checking Atlas model")
    hf_cache = Path.home() / ".cache" / "huggingface"
    hf_cache.mkdir(parents=True, exist_ok=True)
    if _atlas_model_cached(cfg):
        ok(f"Model cached: {cfg.atlas_model}")
        return

    info(f"Downloading {cfg.atlas_model} into HF cache  (~46 GB NVFP4 — grab a coffee)")
    py_cmd = (
        "from huggingface_hub import snapshot_download; "
        "snapshot_download('" + cfg.atlas_model + "')"
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
    ok(f"Downloaded: {cfg.atlas_model}")


def pull_atlas_image(cfg, docker_cmd):
    section("Pulling Atlas image")
    force_pull = os.environ.get("ATLAS_PULL", "").lower() in (
        "always",
        "1",
        "true",
        "yes",
    )
    if not force_pull and _image_exists_locally(docker_cmd, cfg.atlas_image):
        ok(f"Image cached locally: {cfg.atlas_image}")
        return

    info(f"Image: {cfg.atlas_image}  (~2.5 GB on first pull)")
    try:
        run([*docker_cmd, "pull", cfg.atlas_image])
        ok("Image ready")
    except subprocess.CalledProcessError:
        if _image_exists_locally(docker_cmd, cfg.atlas_image):
            warn("Pull failed — using local image")
            ok(f"Image cached locally: {cfg.atlas_image}")
        else:
            raise


def _atlas_serve_args(cfg) -> list:
    args = [
        "serve",
        cfg.atlas_model,
        "--port",
        str(cfg.atlas_port),
        "--max-seq-len",
        str(cfg.atlas_max_seq_len),
        "--kv-cache-dtype",
        str(cfg.atlas_kv_cache_dtype),
        "--gpu-memory-utilization",
        str(cfg.atlas_gpu_mem_util),
        "--scheduling-policy",
        "slai",
        "--tool-call-parser",
        "qwen3_coder",
        "--enable-prefix-caching",
    ]
    if cfg.atlas_kv_cache_dtype != "bf16":
        args.extend(["--kv-high-precision-layers", "auto"])
    if cfg.atlas_speculative:
        args.extend(["--speculative", "--num-drafts", str(cfg.atlas_num_drafts)])
    if cfg.atlas_max_thinking_budget > 0:
        args.extend(["--max-thinking-budget", str(cfg.atlas_max_thinking_budget)])
    return args


def _atlas_launch_fingerprint(cfg) -> str:
    payload = json.dumps(
        {
            "image": cfg.atlas_image,
            "model": cfg.atlas_model,
            "port": cfg.atlas_port,
            "serve": _atlas_serve_args(cfg),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def start_atlas(cfg, docker_cmd) -> str:
    """Start or reuse the Atlas container."""
    spec = (
        f"MTP K={cfg.atlas_num_drafts}" if cfg.atlas_speculative else "no speculative"
    )
    section(f"Starting Atlas  [{cfg.atlas_model}, {spec}]")
    info(
        f"Context: {cfg.atlas_max_seq_len} tokens  |  KV: {cfg.atlas_kv_cache_dtype}  |  "
        f"GPU budget: {cfg.atlas_gpu_mem_util:.0%}"
    )
    info("Atlas cold-starts in <2 min (no torch.compile)")

    force_restart = _should_remove_container(cfg)
    status = _container_status(cfg)
    fingerprint = _atlas_launch_fingerprint(cfg)

    if not force_restart and status == "running":
        if _atlas_ready(cfg):
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
    hf_cache = Path.home() / ".cache" / "huggingface"
    hf_cache.mkdir(parents=True, exist_ok=True)

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
            "-v",
            f"{hf_cache}:/root/.cache/huggingface",
            "-e",
            "HF_TOKEN=" + cfg.hf_token,
            "-e",
            "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
            cfg.atlas_image,
            *_atlas_serve_args(cfg),
        ]
    )
    ok(f"Container '{cfg.container_name}' started")
    return "started"
