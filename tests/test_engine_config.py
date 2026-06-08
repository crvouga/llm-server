import importlib
import os
import sys
from pathlib import Path


def _load_spark():
    server_dir = Path(__file__).resolve().parents[1] / "server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    return importlib.import_module("spark")


def test_default_engine_is_vllm():
    mod = _load_spark()
    cfg = mod.config.Config()
    mod.config._apply_env_overrides(cfg)
    assert cfg.engine == "vllm"
    assert cfg.container_name == "vllm"
    assert cfg.service_port == 8888


def test_engine_atlas_legacy_env():
    mod = _load_spark()
    os.environ["ENGINE"] = "atlas"
    try:
        cfg = mod.config.Config()
        mod.config._apply_env_overrides(cfg)
        assert cfg.engine == "atlas"
        assert cfg.container_name == "atlas"
        assert cfg.service_port == cfg.atlas_port
    finally:
        os.environ.pop("ENGINE", None)


def test_vllm_serve_args_include_tool_parser_and_dflash():
    mod = _load_spark()
    engine_vllm = importlib.import_module("spark.engine_vllm")
    cfg = mod.config.Config()
    mod.config._apply_env_overrides(cfg)
    args = engine_vllm._vllm_serve_args(cfg)
    assert "serve" in args
    assert cfg.vllm_model in args
    assert "--tool-call-parser" in args
    assert args[args.index("--tool-call-parser") + 1] == "qwen3_coder"
    assert "--served-model-name" in args
    assert args[args.index("--served-model-name") + 1] == "atlas"
    assert "--speculative-config" in args
    spec = args[args.index("--speculative-config") + 1]
    assert "dflash" in spec
    assert cfg.vllm_dflash_model in spec


def test_vllm_no_speculative_when_disabled():
    mod = _load_spark()
    engine_vllm = importlib.import_module("spark.engine_vllm")
    os.environ["VLLM_NO_SPECULATIVE"] = "1"
    try:
        cfg = mod.config.Config()
        mod.config._apply_env_overrides(cfg)
        args = engine_vllm._vllm_serve_args(cfg)
        assert "--speculative-config" not in args
    finally:
        os.environ.pop("VLLM_NO_SPECULATIVE", None)
