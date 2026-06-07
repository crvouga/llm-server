import importlib.util
import os
from pathlib import Path
from unittest import mock

import pytest


def _load_server():
    path = Path(__file__).resolve().parents[1] / "server" / "server.py"
    spec = importlib.util.spec_from_file_location("spark_serve", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg(mod, tmp_path: Path):
    cfg = mod.Config()
    cfg.model_dir = tmp_path / "models"
    cfg.model_dir.mkdir(parents=True, exist_ok=True)
    (cfg.model_dir / "main").mkdir(exist_ok=True)
    (cfg.model_dir / "drafter").mkdir(exist_ok=True)
    cfg.compile_cache_dir = tmp_path / "compile"
    return cfg


def test_compile_cache_populated_requires_artifact_subdir(tmp_path):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)

    assert mod._compile_cache_populated(cfg) is False

    inductor = cfg.compile_cache_dir / "torchinductor" / "abc"
    inductor.mkdir(parents=True)
    (inductor / "kernel.so").write_text("x")
    assert mod._compile_cache_populated(cfg) is True


def test_vllm_launch_fingerprint_stable(tmp_path):
    mod = _load_server()
    cfg_a = _cfg(mod, tmp_path)
    cfg_b = _cfg(mod, tmp_path)

    assert mod._vllm_launch_fingerprint(cfg_a) == mod._vllm_launch_fingerprint(cfg_b)

    cfg_b.optimization_level = 2
    assert mod._vllm_launch_fingerprint(cfg_a) != mod._vllm_launch_fingerprint(cfg_b)


def test_resolve_optimization_profile_cold_cache(tmp_path, monkeypatch):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    cfg.gpu_exclusive = True
    monkeypatch.delenv("VLLM_PRODUCTION", raising=False)
    monkeypatch.delenv("VLLM_OPTIMIZATION_LEVEL", raising=False)
    monkeypatch.delenv("VLLM_FAST_BOOT", raising=False)

    mod._resolve_optimization_profile(cfg)
    assert cfg.optimization_level == 1
    assert "cold cache" in cfg.boot_profile


def test_resolve_optimization_profile_warm_exclusive_gpu(tmp_path, monkeypatch):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    cfg.gpu_exclusive = True
    cache = cfg.compile_cache_dir / "triton" / "x"
    cache.mkdir(parents=True)
    (cache / "a.bin").write_bytes(b"\x00")
    monkeypatch.delenv("VLLM_PRODUCTION", raising=False)
    monkeypatch.delenv("VLLM_OPTIMIZATION_LEVEL", raising=False)
    monkeypatch.delenv("VLLM_FAST_BOOT", raising=False)

    mod._resolve_optimization_profile(cfg)
    assert cfg.optimization_level == 2
    assert cfg.max_batched_tokens == 32768
    assert "exclusive GPU" in cfg.boot_profile


def test_resolve_optimization_profile_fast_boot(tmp_path, monkeypatch):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    monkeypatch.setenv("VLLM_FAST_BOOT", "1")
    monkeypatch.delenv("VLLM_PRODUCTION", raising=False)
    monkeypatch.delenv("VLLM_OPTIMIZATION_LEVEL", raising=False)

    mod._resolve_optimization_profile(cfg)
    assert cfg.optimization_level == 0


def test_check_gpu_memory_fail_fast(tmp_path, monkeypatch):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    monkeypatch.delenv("VLLM_ALLOW_GPU_SHARING", raising=False)
    mod._gpu_probe_cache = (40 * 1024**3, 120 * 1024**3)

    with pytest.raises(SystemExit):
        mod._check_gpu_memory(cfg, ["docker"])


def test_check_gpu_memory_allow_sharing_lowers_util(tmp_path, monkeypatch):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    monkeypatch.setenv("VLLM_ALLOW_GPU_SHARING", "1")
    mod._gpu_probe_cache = (90 * 1024**3, 120 * 1024**3)

    mod._check_gpu_memory(cfg, ["docker"])
    assert cfg.gpu_exclusive is False
    assert cfg.gpu_mem_util < 0.85


def test_ingress_already_routed():
    mod = _load_server()
    existing = [
        {"hostname": "vllm.chrisvouga.dev", "service": "http://127.0.0.1:8000"},
        {"service": "http_status:404"},
    ]
    assert mod._ingress_already_routed(
        existing, "vllm.chrisvouga.dev", "http://127.0.0.1:8000"
    )
    assert not mod._ingress_already_routed(
        existing, "vllm.chrisvouga.dev", "http://127.0.0.1:1234"
    )


def test_health_max_wait_scales_with_optimization_level(tmp_path):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    cfg.optimization_level = 0
    assert mod._health_max_wait(cfg) == 180
    cfg.optimization_level = 2
    assert mod._health_max_wait(cfg) == 720


def test_should_remove_container_env(tmp_path, monkeypatch):
    mod = _load_server()
    cfg = _cfg(mod, tmp_path)
    monkeypatch.delenv("VLLM_REMOVE_CONTAINER", raising=False)
    monkeypatch.delenv("VLLM_FORCE_RESTART", raising=False)
    assert mod._should_remove_container(cfg) is False

    monkeypatch.setenv("VLLM_REMOVE_CONTAINER", "1")
    assert mod._should_remove_container(cfg) is True
