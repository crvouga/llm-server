import importlib
import json
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
    assert cfg.vllm_model == "RedHatAI/Qwen3-Coder-Next-NVFP4"


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


def test_vllm_serve_args_include_tool_parser_no_spec_on_ngc_image():
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
    assert "--speculative-config" not in args


def test_vllm_serve_args_use_mtp_on_midtier_image():
    mod = _load_spark()
    engine_vllm = importlib.import_module("spark.engine_vllm")
    cfg = mod.config.Config()
    cfg.vllm_image = "vllm/vllm-openai:v0.18.0-cu130"
    mod.config._apply_env_overrides(cfg)
    args = engine_vllm._vllm_serve_args(cfg)
    spec = args[args.index("--speculative-config") + 1]
    assert '"method":"mtp"' in spec.replace(" ", "")
    assert str(cfg.vllm_mtp_tokens) in spec


def test_vllm_serve_args_use_dflash_on_newer_image():
    mod = _load_spark()
    engine_vllm = importlib.import_module("spark.engine_vllm")
    cfg = mod.config.Config()
    cfg.vllm_image = "vllm/vllm-openai:v0.20.0-cu130"
    mod.config._apply_env_overrides(cfg)
    args = engine_vllm._vllm_serve_args(cfg)
    spec = args[args.index("--speculative-config") + 1]
    assert "dflash" in spec
    assert cfg.vllm_dflash_model in spec


def test_vllm_quant_config_compat_strips_scale_dtype():
    mod = _load_spark()
    model_compat = importlib.import_module("spark.model_compat")
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        snap = (
            Path(tmp)
            / "hub"
            / "models--RedHatAI--Qwen3-Coder-Next-NVFP4"
            / "snapshots"
            / "abc123"
        )
        snap.mkdir(parents=True)
        config = {
            "quantization_config": {
                "config_groups": {
                    "group_0": {
                        "input_activations": {
                            "scale_dtype": "torch.float8_e4m3fn",
                            "zp_dtype": None,
                        }
                    }
                }
            }
        }
        (snap / "config.json").write_text(json.dumps(config))
        original = model_compat._repo_snapshot_dir
        model_compat._repo_snapshot_dir = lambda _m: snap
        try:
            cfg = mod.config.Config()
            cfg.helper_dir = Path(tmp) / "helper"
            model_compat.ensure_vllm_quant_config_compat(cfg)
        finally:
            model_compat._repo_snapshot_dir = original

        patched_path = model_compat._vllm_compat_config_path(cfg)
        patched = json.loads(patched_path.read_text())
        group = patched["quantization_config"]["config_groups"]["group_0"][
            "input_activations"
        ]
        assert "scale_dtype" not in group
        assert "zp_dtype" not in group
        mount = model_compat.vllm_quant_config_mount(cfg)
        assert mount is not None


def test_hf_download_failure_hint_gated_repo():
    mod = _load_spark()
    engine_vllm = importlib.import_module("spark.engine_vllm")
    output = (
        "GatedRepoError: 403 Client Error.\n"
        "you are not in the authorized list."
    )
    hint = engine_vllm._hf_download_failure_hint(
        "saricles/Qwen3-Coder-Next-NVFP4-GB10", output
    )
    assert hint is not None
    assert "gated" in hint.lower()
    assert "VLLM_MODEL=" in hint


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
