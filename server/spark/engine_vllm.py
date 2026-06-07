"""vLLM + DFlash engine: image pull, container launch, warmup (fallback path)."""

import hashlib
import json
import os
import subprocess
import urllib.request

from .compile_cache import _compile_cache_populated, _prepare_compile_cache_dir
from .config import _boot_time_hint, _should_remove_container
from .console import info, ok, section, warn
from .constants import _CONFIG_HASH_LABEL, _SERVED_MODEL, _WARMUP_PROMPT
from .containers import (
    _container_config_hash,
    _container_restart_count,
    _container_status,
    _image_exists_locally,
    remove_container,
)
from .gpu import _gpu_run_flags
from .health import _vllm_ready
from .models import (
    _drafter_path,
    _model_native_context,
    _model_path,
    _rope_scaling_json,
)
from .runtime import register_container
from .shell import run


def _speculative_config_json(cfg) -> str:
    return json.dumps(
        {
            "method": "dflash",
            "model": "/models/drafter",
            "num_speculative_tokens": cfg.dflash_num_spec_tokens,
        },
        sort_keys=True,
    )


def _vllm_launch_fingerprint(cfg) -> str:
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
            "attention_backend": cfg.attention_backend,
            "flashinfer_moe_fp4": cfg.flashinfer_moe_fp4,
            "flashinfer_moe_backend": cfg.flashinfer_moe_backend,
            "native_context_len": _model_native_context(cfg),
            "port": cfg.vllm_port,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


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


def start_vllm(cfg, docker_cmd) -> str:
    """Start or reuse the vLLM container (see return values in main())."""
    section(
        f"Starting vLLM + DFlash  [Qwen3.6-35B-A3B NVFP4, k={cfg.dflash_num_spec_tokens}]"
    )
    info("Target: 120-128 tok/s single-stream + high aggregate across parallel agents")
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
        if _vllm_ready(cfg):
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
            f"(YaRN {json.loads(rope_config)['rope_parameters']['factor']}x over native {native_ctx})"
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
            str(cfg.attention_backend),
            "--speculative-config",
            spec_config,
    ]
    if rope_config:
        vllm_serve_args.extend(["--hf-overrides", rope_config])
    if cfg.kv_cache_dtype and cfg.kv_cache_dtype != "auto":
        vllm_serve_args.extend(["--kv-cache-dtype", str(cfg.kv_cache_dtype)])

    moe_env: list[str] = []
    if cfg.flashinfer_moe_fp4:
        info(
            f"Experimental: FlashInfer NVFP4 MoE backend "
            f"({cfg.flashinfer_moe_backend}) instead of Marlin"
        )
        moe_env = [
            "-e",
            "VLLM_USE_FLASHINFER_MOE_FP4=1",
            "-e",
            f"VLLM_FLASHINFER_MOE_BACKEND={cfg.flashinfer_moe_backend}",
        ]

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
            *moe_env,
            cfg.vllm_image,
            # Match AEON-7 docker-compose.yml — NVFP4 needs compressed-tensors
            *vllm_serve_args,
        ]
    )
    ok(f"Container '{cfg.container_name}' started")
    return "started"


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
