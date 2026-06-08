"""Atlas weight-compat for RedHatAI compressed-tensors NVFP4 checkpoints.

Atlas's qwen3_next loader expects BF16 ``.weight`` tensors for full-attention
Q/K/V projections and runtime-quantizes them. RedHatAI/Qwen3-Coder-Next-NVFP4
ships those projections as on-disk NVFP4 (``.weight_packed`` only), which makes
Atlas fail at layer 3 with ``Weight '...q_proj.weight' not found in store``.

Atlas fast-loads only the numbered checkpoint shards (``model-*-of-00010``), so
compat weights must be merged into one of those shards — a standalone sidecar
file is indexed but never loaded into the weight store.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from .console import info, ok, section
from .shell import run

_COMPAT_MARKER = ".atlas-attn-weight-compat-v2"
_LEGACY_MARKER = ".atlas-attn-weight-compat-v1"
_LEGACY_SIDECAR = "atlas-attn-weight-compat.safetensors"
_MERGE_SHARD = "model-00010-of-00010.safetensors"
_COMPAT_MODELS = frozenset({"redhatai/qwen3-coder-next-nvfp4"})
_VLLM_QUANT_COMPAT_MARKER = ".vllm-quant-config-compat-v1"
# vLLM 0.13 (NVIDIA 26.01) rejects newer compressed-tensors metadata.
_VLLM_QUANT_COMPAT_IMAGES = ("nvcr.io/nvidia/vllm:26.01",)

# Runs inside python:3.11-slim (same image family as HF snapshot_download).
_COMPAT_SCRIPT = textwrap.dedent(
    r'''
    import json
    from pathlib import Path

    import numpy as np
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    MARKER = ".atlas-attn-weight-compat-v2"
    LEGACY_MARKER = ".atlas-attn-weight-compat-v1"
    LEGACY_SIDECAR = "atlas-attn-weight-compat.safetensors"
    MERGE_SHARD = "model-00010-of-00010.safetensors"

    E2M1_LUT = np.array(
        [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0],
        dtype=np.float32,
    )

    def dequant_nvfp4(packed: np.ndarray, scale: np.ndarray, global_scale: np.ndarray) -> torch.Tensor:
        packed_u8 = packed.astype(np.uint8)
        n, half_k = packed_u8.shape
        k = half_k * 2
        group = 16
        scale2 = 1.0 / float(global_scale.reshape(-1)[0])

        lo = packed_u8 & 0x0F
        hi = packed_u8 >> 4
        lo_idx = lo & 0x7
        hi_idx = hi & 0x7
        lo_sign = np.where(lo & 0x8, -1.0, 1.0).astype(np.float32)
        hi_sign = np.where(hi & 0x8, -1.0, 1.0).astype(np.float32)
        lo_val = lo_sign * E2M1_LUT[lo_idx]
        hi_val = hi_sign * E2M1_LUT[hi_idx]
        vals = np.empty((n, k), dtype=np.float32)
        vals[:, 0::2] = lo_val
        vals[:, 1::2] = hi_val

        block_scales = scale.astype(np.float32)
        vals *= block_scales[:, np.arange(k) // group]
        vals *= scale2
        return torch.tensor(vals, dtype=torch.float32).to(torch.bfloat16)

    def main() -> None:
        snap = Path(__import__("sys").argv[1])
        marker = snap / MARKER
        if marker.exists():
            return

        index_path = snap / "model.safetensors.index.json"
        index = json.loads(index_path.read_text())
        weight_map = dict(index["weight_map"])

        targets: list[str] = []
        for key in list(weight_map):
            if ".self_attn." not in key or not key.endswith(".weight_packed"):
                continue
            base = key[: -len(".weight_packed")]
            weight_key = base + ".weight"
            proj = base.split(".")[-1]
            if proj not in {"q_proj", "k_proj", "v_proj"}:
                continue
            mapped = weight_map.get(weight_key)
            if mapped is None or mapped == LEGACY_SIDECAR:
                targets.append(base)

        if not targets:
            marker.write_text("noop\n")
            return

        new_weights: dict[str, torch.Tensor] = {}
        for base in sorted(targets):
            packed_key = base + ".weight_packed"
            scale_key = base + ".weight_scale"
            gscale_key = base + ".weight_global_scale"
            shard = snap / weight_map[packed_key]
            with safe_open(shard, framework="pt") as f:
                packed = f.get_tensor(packed_key).to(torch.uint8).cpu().numpy()
                scale = f.get_tensor(scale_key).to(torch.float32).cpu().numpy()
                gscale = f.get_tensor(gscale_key).to(torch.float32).cpu().numpy()
            weight_key = base + ".weight"
            new_weights[weight_key] = dequant_nvfp4(packed, scale, gscale)
            weight_map[weight_key] = MERGE_SHARD

        merge_path = snap / MERGE_SHARD
        merged: dict[str, torch.Tensor] = {}
        with safe_open(merge_path, framework="pt") as f:
            for key in f.keys():
                merged[key] = f.get_tensor(key)
        merged.update(new_weights)

        if merge_path.is_symlink():
            merge_path.unlink()
        save_file(merged, merge_path)

        legacy_sidecar = snap / LEGACY_SIDECAR
        if legacy_sidecar.exists():
            legacy_sidecar.unlink()
        legacy_marker = snap / LEGACY_MARKER
        if legacy_marker.exists():
            legacy_marker.unlink()

        metadata = index.get("metadata") or {}
        total = sum((snap / shard).resolve().stat().st_size for shard in set(weight_map.values()))
        metadata["total_size"] = total
        index["metadata"] = metadata
        index["weight_map"] = weight_map
        index_path.write_text(json.dumps(index, indent=2) + "\n")
        marker.write_text(f"layers={len(targets)} shard={MERGE_SHARD}\n")

    if __name__ == "__main__":
        main()
    '''
)


def _repo_snapshot_dir(model_id: str) -> Path | None:
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = hub / ("models--" + model_id.replace("/", "--"))
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = [p for p in snapshots.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _snapshot_dir(cfg) -> Path | None:
    return _repo_snapshot_dir(cfg.atlas_model)


def _strip_unsupported_quant_fields(node: object) -> bool:
    """Remove scale_dtype/zp_dtype keys vLLM 0.13 rejects. Returns True if changed."""
    changed = False
    if isinstance(node, dict):
        for key in ("scale_dtype", "zp_dtype"):
            if key in node:
                del node[key]
                changed = True
        for value in node.values():
            if _strip_unsupported_quant_fields(value):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if _strip_unsupported_quant_fields(item):
                changed = True
    return changed


def _config_has_unsupported_quant_fields(node: object) -> bool:
    if isinstance(node, dict):
        if "scale_dtype" in node or "zp_dtype" in node:
            return True
        return any(_config_has_unsupported_quant_fields(v) for v in node.values())
    if isinstance(node, list):
        return any(_config_has_unsupported_quant_fields(item) for item in node)
    return False


def needs_vllm_quant_config_compat(cfg) -> bool:
    if not any(tag in cfg.vllm_image.lower() for tag in _VLLM_QUANT_COMPAT_IMAGES):
        return False
    if cfg.vllm_model.lower() not in _COMPAT_MODELS:
        return False
    if _vllm_compat_config_path(cfg).is_file():
        return False
    snap = _repo_snapshot_dir(cfg.vllm_model)
    if snap is None:
        return False
    config_path = snap / "config.json"
    if not config_path.is_file():
        return False
    return _config_has_unsupported_quant_fields(json.loads(config_path.read_text()))


def _vllm_compat_config_path(cfg) -> Path:
    return (
        cfg.helper_dir
        / "vllm-quant-compat"
        / cfg.vllm_model.replace("/", "--")
        / "config.json"
    )


def vllm_quant_config_mount(cfg) -> tuple[Path, Path] | None:
    """Return host + container config paths when a compat overlay is active."""
    patched = _vllm_compat_config_path(cfg)
    if not patched.is_file():
        return None
    snap = _repo_snapshot_dir(cfg.vllm_model)
    if snap is None:
        return None
    container = Path("/root/.cache/huggingface/hub") / (
        "models--" + cfg.vllm_model.replace("/", "--")
    ) / "snapshots" / snap.name / "config.json"
    return patched, container


def ensure_vllm_quant_config_compat(cfg) -> None:
    """Materialize a vLLM 0.13-safe config.json overlay for RedHatAI NVFP4."""
    if not needs_vllm_quant_config_compat(cfg):
        return

    snap = _repo_snapshot_dir(cfg.vllm_model)
    if snap is None:
        return

    patched_path = _vllm_compat_config_path(cfg)
    if patched_path.is_file():
        ok("Quant config compat ready")
        return

    section("Preparing vLLM quant config compat")
    info(
        "RedHatAI NVFP4 config includes scale_dtype/zp_dtype metadata; "
        "writing a vLLM 0.13-safe overlay"
    )

    config = json.loads((snap / "config.json").read_text())
    if not _strip_unsupported_quant_fields(config):
        ok("Quant config compat ready (no changes needed)")
        (snap / _VLLM_QUANT_COMPAT_MARKER).touch()
        return

    patched_path.parent.mkdir(parents=True, exist_ok=True)
    patched_path.write_text(json.dumps(config, indent=2) + "\n")
    ok(f"Quant config compat ready ({patched_path})")


def _index_needs_compat(index: dict) -> bool:
    weight_map = index.get("weight_map", {})
    if any(v == _LEGACY_SIDECAR for v in weight_map.values()):
        return True
    for key in weight_map:
        if ".self_attn." not in key or not key.endswith(".weight_packed"):
            continue
        base = key[: -len(".weight_packed")]
        if base.split(".")[-1] not in {"q_proj", "k_proj", "v_proj"}:
            continue
        if base + ".weight" not in weight_map:
            return True
    return False


def needs_atlas_weight_compat(cfg) -> bool:
    if cfg.atlas_model.lower() not in _COMPAT_MODELS:
        return False
    snap = _snapshot_dir(cfg)
    if snap is None:
        return False
    if (snap / _COMPAT_MARKER).exists():
        return False
    if (snap / _LEGACY_MARKER).exists() or (snap / _LEGACY_SIDECAR).exists():
        return True
    index_path = snap / "model.safetensors.index.json"
    if not index_path.is_file():
        return False
    return _index_needs_compat(json.loads(index_path.read_text()))


def ensure_atlas_weight_compat(cfg, docker_cmd) -> None:
    """Materialize BF16 attention weights Atlas needs for RedHatAI NVFP4."""
    if not needs_atlas_weight_compat(cfg):
        return

    snap = _snapshot_dir(cfg)
    if snap is None:
        return

    section("Preparing Atlas weight compat")
    info(
        "RedHatAI NVFP4 stores attention Q/K/V as weight_packed only; "
        f"merging dequantized BF16 .weight tensors into {_MERGE_SHARD}"
    )

    hf_cache = Path.home() / ".cache" / "huggingface"
    script_path = hf_cache / "_atlas_attn_weight_compat.py"
    script_path.write_text(_COMPAT_SCRIPT)

    run(
        [
            *docker_cmd,
            "run",
            "--rm",
            "-v",
            f"{hf_cache}:/root/.cache/huggingface",
            "-v",
            f"{script_path}:/compat.py:ro",
            "python:3.11-slim",
            "bash",
            "-c",
            "pip install -q safetensors numpy packaging && "
            "pip install -q torch --index-url https://download.pytorch.org/whl/cpu && "
            f"python /compat.py /root/.cache/huggingface/hub/"
            f"models--{cfg.atlas_model.replace('/', '--')}/snapshots/{snap.name}",
        ]
    )
    ok(f"Weight compat ready (merged into {_MERGE_SHARD})")
