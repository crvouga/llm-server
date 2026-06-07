import importlib.util
from pathlib import Path


def _load_server():
    path = Path(__file__).resolve().parents[1] / "server" / "server.py"
    spec = importlib.util.spec_from_file_location("spark_serve", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_merge_tunnel_ingress_replaces_existing_hostname():
    mod = _load_server()
    existing = [
        {"hostname": "vllm.chrisvouga.dev", "service": "http://127.0.0.1:1234"},
        {"service": "http_status:404"},
    ]
    merged = mod.merge_tunnel_ingress(
        existing, "vllm.chrisvouga.dev", "http://127.0.0.1:8000"
    )
    assert merged[0]["service"] == "http://127.0.0.1:8000"
    assert merged[-1] == {"service": "http_status:404"}


def test_merge_tunnel_ingress_appends_new_hostname():
    mod = _load_server()
    merged = mod.merge_tunnel_ingress(
        [{"service": "http_status:404"}],
        "vllm.chrisvouga.dev",
        "http://127.0.0.1:8000",
    )
    assert merged[0]["hostname"] == "vllm.chrisvouga.dev"
    assert merged[-1] == {"service": "http_status:404"}


def test_tunnel_ingress_from_config_response_null_result():
    mod = _load_server()
    assert mod._tunnel_ingress_from_config_response({"result": None}) == []


def test_tunnel_ingress_from_config_response_null_config():
    mod = _load_server()
    resp = {
        "result": {
            "tunnel_id": "3ad67333-bc04-4125-aacb-c423edc71535",
            "version": 0,
            "config": None,
            "source": "cloudflare",
        }
    }
    assert mod._tunnel_ingress_from_config_response(resp) == []


def test_tunnel_ingress_from_config_response_missing_result():
    mod = _load_server()
    assert mod._tunnel_ingress_from_config_response({}) == []


def test_tunnel_ingress_from_config_response_existing_ingress():
    mod = _load_server()
    ingress = [
        {"hostname": "vllm.chrisvouga.dev", "service": "http://127.0.0.1:8000"},
        {"service": "http_status:404"},
    ]
    resp = {"result": {"config": {"ingress": ingress}}}
    assert mod._tunnel_ingress_from_config_response(resp) == ingress
