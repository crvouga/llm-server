"""vLLM torch/Triton compile-cache management + boot optimization profile.

Only used by the vLLM engine path; Atlas has no compile step.
"""

import os
import shutil
import subprocess
from pathlib import Path

from .console import die, info, ok, section, warn
from .constants import _COMPILE_CACHE_SUBDIRS


def _compile_cache_populated(cfg) -> bool:
    if not cfg.compile_cache_dir.is_dir():
        return False
    for sub in ("torchinductor", "triton"):
        d = cfg.compile_cache_dir / sub
        if d.is_dir() and any(d.rglob("*")):
            return True
    compile_root = cfg.compile_cache_dir / "torch_compile_cache"
    return compile_root.is_dir() and any(compile_root.rglob("*"))


def _prepare_compile_cache_dir(cfg, docker_cmd: list | None = None) -> None:
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


def _clear_compile_cache(cfg) -> None:
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


def _repair_triton_cache(cfg) -> int:
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


def _ensure_compile_cache(cfg, docker_cmd: list | None = None) -> None:
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


def _resolve_optimization_profile(cfg) -> None:
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
