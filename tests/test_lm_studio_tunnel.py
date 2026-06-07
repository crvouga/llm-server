import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_lmstudio():
    repo = Path(__file__).resolve().parents[1]
    for sub in ("server", "lm-studio"):
        p = str(repo / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module("lmstudio.config"), importlib.import_module(
        "lmstudio.prechecks"
    )


def test_config_defaults():
    config_mod, _ = _load_lmstudio()
    cfg = config_mod.Config()
    assert cfg.lm_studio_port == 1234
    assert cfg.cf_tunnel_hostname == "llm.chrisvouga.dev"
    assert cfg.cf_tunnel_name == "llm"
    assert cfg.service_port == 1234
    assert cfg.helper_dir == Path.home() / ".lm-studio-tunnel"


def test_apply_env_overrides():
    config_mod, _ = _load_lmstudio()
    cfg = config_mod.Config()
    with patch.dict(
        "os.environ",
        {
            "LM_STUDIO_PORT": "5678",
            "CF_TUNNEL_HOSTNAME": "test.example.com",
            "CF_TUNNEL_NAME": "test-tunnel",
        },
    ):
        config_mod.apply_env_overrides(cfg)
    assert cfg.lm_studio_port == 5678
    assert cfg.cf_tunnel_hostname == "test.example.com"
    assert cfg.cf_tunnel_name == "test-tunnel"
    assert cfg.service_port == 5678


def test_spark_server_running_ignores_stop_subcommand():
    _, prechecks_mod = _load_lmstudio()
    with patch.object(prechecks_mod.Path, "home", return_value=Path("/nonexistent")):
        with patch(
            "lmstudio.prechecks.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="999\n"),
        ):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = (
                    b"python3\x00server/server.py\x00--stop"
                )
                assert prechecks_mod._spark_server_running() is False


def test_spark_server_running_detects_main_server():
    _, prechecks_mod = _load_lmstudio()
    with patch.object(prechecks_mod.Path, "home", return_value=Path("/nonexistent")):
        with patch(
            "lmstudio.prechecks.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="999\n"),
        ):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = (
                    b"python3\x00server/server.py"
                )
                assert prechecks_mod._spark_server_running() is True


def test_precheck_lm_studio_returns_model_ids():
    _, prechecks_mod = _load_lmstudio()
    config_mod, _ = _load_lmstudio()
    cfg = config_mod.Config()

    payload = b'{"data": [{"id": "my-model"}, {"id": "other"}]}'
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("lmstudio.prechecks.urllib.request.urlopen", return_value=mock_resp):
        models = prechecks_mod.precheck_lm_studio(cfg)
    assert models == ["my-model", "other"]
