"""Atlas weight-compat for RedHatAI compressed-tensors NVFP4 checkpoints.

Atlas's qwen3_next loader expects BF16 ``.weight`` tensors for full-attention
Q/K/V projections and runtime-quantizes them. RedHatAI/Qwen3-Coder-Next-NVFP4
ships those projections as on-disk NVFP4 (``.weight_packed`` only), which makes
Atlas fail at layer 3 with ``Weight '...q_proj.weight' not found in store``.

This module materializes the missing BF16 tensors into a small sidecar shard and
updates the HF index once per snapshot.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from .console import info, ok, section
from .shell import run

_COMPAT_MARKER = ".atlas-attn-weight-compat-v1"
_COMPAT_SHARD = "atlas-attn-weight-compat.safetensors"
_COMPAT_MODELS = frozenset({"redhatai/qwen3-coder-next-nvfp4"})

# Runs inside python:3.11-slim (same image family as HF snapshot_download).
_COMPAT_SCRIPT = textwrap.dedent(
    r'''
    import json
    from pathlib import Path

    import numpy as np
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

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
        marker = snap / ".atlas-attn-weight-compat-v1"
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
            if weight_key not in weight_map and base.split(".")[-1] in {"q_proj", "k_proj", "v_proj"}:
                targets.append(base)

        if not targets:
            marker.write_text("noop\n")
            return

        tensors: dict[str, torch.Tensor] = {}
        for base in sorted(targets):
            packed_key = base + ".weight_packed"
            scale_key = base + ".weight_scale"
            gscale_key = base + ".weight_global_scale"
            shard = snap / weight_map[packed_key]
            with safe_open(shard, framework="pt") as f:
                packed = f.get_tensor(packed_key).to(torch.uint8).cpu().numpy()
                scale = (
                    f.get_tensor(scale_key).to(torch.float32).cpu().numpy()
                )
                gscale = f.get_tensor(gscale_key).to(torch.float32).cpu().numpy()
            weight_key = base + ".weight"
            tensors[weight_key] = dequant_nvfp4(packed, scale, gscale)
            weight_map[weight_key] = "atlas-attn-weight-compat.safetensors"

        compat_path = snap / "atlas-attn-weight-compat.safetensors"
        save_file(tensors, compat_path)

        metadata = index.get("metadata") or {}
        total = int(metadata.get("total_size", 0))
        total += compat_path.stat().st_size
        metadata["total_size"] = total
        index["metadata"] = metadata
        index["weight_map"] = weight_map
        index_path.write_text(json.dumps(index, indent=2) + "\n")
        marker.write_text(f"layers={len(targets)}\n")

    if __name__ == "__main__":
        main()
    '''
)


def _snapshot_dir(cfg) -> Path | None:
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = hub / ("models--" + cfg.atlas_model.replace("/", "--"))
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = [p for p in snapshots.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def needs_atlas_weight_compat(cfg) -> bool:
    if cfg.atlas_model.lower() not in _COMPAT_MODELS:
        return False
    snap = _snapshot_dir(cfg)
    if snap is None:
        return False
    if (snap / _COMPAT_MARKER).exists():
        return False
    index_path = snap / "model.safetensors.index.json"
    if not index_path.is_file():
        return False
    index = json.loads(index_path.read_text())
    for key in index.get("weight_map", {}):
        if ".self_attn." not in key or not key.endswith(".weight_packed"):
            continue
        base = key[: -len(".weight_packed")]
        if base.split(".")[-1] not in {"q_proj", "k_proj", "v_proj"}:
            continue
        if base + ".weight" not in index["weight_map"]:
            return True
    return False


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
        "materializing BF16 .weight sidecar for Atlas"
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
    ok(f"Weight compat ready ({_COMPAT_SHARD})")
