"""vLLM model paths, YaRN rope scaling, and HF downloads (vLLM engine only).

Atlas auto-downloads its checkpoint into the HF cache, so none of this runs for it.
"""

import json
import math
import os
from pathlib import Path

from .console import die, info, ok, section, warn
from .constants import _DEFAULT_NATIVE_CONTEXT
from .shell import run


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


def _model_native_context(cfg) -> int:
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


def _rope_scaling_json(cfg) -> str:
    if not cfg.rope_scaling_enabled:
        return ""
    native = _model_native_context(cfg)
    if cfg.max_model_len <= native:
        return ""
    factor = math.ceil(cfg.max_model_len / native)
    return json.dumps(
        {
            "rope_parameters": {
                "rope_type": "yarn",
                "factor": factor,
                "original_max_position_embeddings": native,
            }
        },
        sort_keys=True,
    )


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
