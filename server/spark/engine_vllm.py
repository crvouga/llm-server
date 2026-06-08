"""vLLM engine: image pull + container launch for GB10/DGX Spark."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .config import _CONFIG_HASH_LABEL, _should_remove_container
from .console import die, info, ok, section, warn
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
from .model_compat import ensure_vllm_quant_config_compat, vllm_quant_config_mount
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


def _hf_download_failure_hint(model_id: str, output: str) -> str | None:
    lower = output.lower()
    if "gatedrepoerror" in lower or "gated repo" in lower or (
        "403" in output and "not in the authorized list" in lower
    ):
        return (
            f"Hugging Face model '{model_id}' is gated and this account is not authorized.\n"
            f"  1. Request access: https://huggingface.co/{model_id}\n"
            "  2. Or pick a public model, e.g.\n"
            "       VLLM_MODEL=unsloth/Qwen3-Coder-Next-FP8-Dynamic make server-start\n"
            "       VLLM_MODEL=RedHatAI/Qwen3-Coder-Next-NVFP4 make server-start"
        )
    if "401" in output and ("unauthorized" in lower or "invalid" in lower):
        return (
            f"Could not authenticate with Hugging Face for '{model_id}'.\n"
            "  Check HF_TOKEN in your secret store (vault) or environment."
        )
    return None


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
    env_args: list[str] = ["-e", "HF_XET_HIGH_PERFORMANCE=1"]
    if cfg.hf_token:
        env_args.extend(
            [
                "-e",
                "HF_TOKEN=" + cfg.hf_token,
                "-e",
                "HUGGING_FACE_HUB_TOKEN=" + cfg.hf_token,
            ]
        )
    result = subprocess.run(
        [
            *docker_cmd,
            "run",
            "--rm",
            "-v",
            f"{hf_cache}:/root/.cache/huggingface",
            *env_args,
            "python:3.11-slim",
            "bash",
            "-c",
            bash_cmd,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        combined = (result.stdout or "") + (result.stderr or "")
        if hint := _hf_download_failure_hint(model_id, combined):
            die(hint)
        tail = combined.strip()[-2000:] or "(no output)"
        die(f"Failed to download {model_id}.\n{tail}")
    ok(f"Downloaded: {model_id}")


def ensure_vllm_model(cfg, docker_cmd):
    """Pre-download target + DFlash drafter into the mounted HF hub cache."""
    section("Checking vLLM models")
    if _hf_repo_cached(cfg.vllm_model):
        ok(f"Target model cached: {cfg.vllm_model}")
    else:
        _download_hf_model(cfg, docker_cmd, cfg.vllm_model, "~43 GB NVFP4")

    ensure_vllm_quant_config_compat(cfg)

    if cfg.vllm_speculative_method_resolved() != "dflash" or not cfg.vllm_dflash_model:
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
    method = cfg.vllm_speculative_method_resolved()
    if not method:
        return None
    if method == "dflash":
        if not cfg.vllm_dflash_model:
            return None
        payload = {
            "method": "dflash",
            "model": cfg.vllm_dflash_model,
            "num_speculative_tokens": cfg.vllm_dflash_tokens,
        }
    elif method in ("mtp", "qwen3_next_mtp"):
        payload = {
            "method": "mtp",
            "num_speculative_tokens": cfg.vllm_mtp_tokens,
        }
    else:
        warn(
            f"Unknown VLLM_SPECULATIVE_METHOD={method!r} — "
            "starting without speculative decoding"
        )
        return None
    return json.dumps(payload, separators=(",", ":"))


def _vllm_speculative_label(cfg) -> str:
    method = cfg.vllm_speculative_method_resolved()
    if not method:
        return "no speculative"
    if method == "dflash" and cfg.vllm_dflash_model:
        return f"DFlash ({cfg.vllm_dflash_model})"
    if method in ("mtp", "qwen3_next_mtp"):
        return f"MTP K={cfg.vllm_mtp_tokens}"
    return method


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
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "qwen3_coder",
        "--enable-prefix-caching",
        "--trust-remote-code",
    ]
    if cfg.vllm_load_format and cfg.vllm_load_format != "auto":
        args.extend(["--load-format", str(cfg.vllm_load_format)])
    if spec := _vllm_speculative_config(cfg):
        args.extend(["--speculative-config", spec])
    if cfg.vllm_enforce_eager:
        args.append("--enforce-eager")
    return args


def _vllm_launch_fingerprint(cfg) -> str:
    compat = vllm_quant_config_mount(cfg)
    payload = json.dumps(
        {
            "image": cfg.vllm_image,
            "model": cfg.vllm_model,
            "speculative": cfg.vllm_speculative_method_resolved(),
            "quant_compat": str(compat[0]) if compat else None,
            "port": cfg.vllm_port,
            "serve": _vllm_serve_args(cfg),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def start_vllm(cfg, docker_cmd) -> str:
    """Start or reuse the vLLM container."""
    section(f"Starting vLLM  [{cfg.vllm_model}, {_vllm_speculative_label(cfg)}]")
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
    if mount := vllm_quant_config_mount(cfg):
        host_config, container_config = mount
        docker_run.extend(
            ["-v", f"{host_config}:{container_config}:ro"]
        )
    # NVIDIA NGC images use ENTRYPOINT ["serve"]; pass "vllm serve <model> ..."
    # explicitly (matches DGX Spark docs).
    docker_run.extend(
        ["--entrypoint", "vllm", cfg.vllm_image, *_vllm_serve_args(cfg)]
    )

    run(docker_run)
    ok(f"Container '{cfg.container_name}' started")
    return "started"
