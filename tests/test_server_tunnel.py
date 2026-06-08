import importlib
import sys
from pathlib import Path


def _load_server():
    # Tunnel ingress helpers now live in the `spark` package (server/spark/).
    server_dir = Path(__file__).resolve().parents[1] / "server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    return importlib.import_module("spark.cloudflare")


def test_merge_tunnel_ingress_replaces_existing_hostname():
    mod = _load_server()
    existing = [
        {"hostname": "llm.chrisvouga.dev", "service": "http://127.0.0.1:1234"},
        {"service": "http_status:404"},
    ]
    merged = mod.merge_tunnel_ingress(
        existing, "llm.chrisvouga.dev", "http://127.0.0.1:8000"
    )
    assert merged[0]["service"] == "http://127.0.0.1:8000"
    assert merged[-1] == {"service": "http_status:404"}


def test_merge_tunnel_ingress_appends_new_hostname():
    mod = _load_server()
    merged = mod.merge_tunnel_ingress(
        [{"service": "http_status:404"}],
        "llm.chrisvouga.dev",
        "http://127.0.0.1:8000",
    )
    assert merged[0]["hostname"] == "llm.chrisvouga.dev"
    assert merged[-1] == {"service": "http_status:404"}


def test_merge_tunnel_ingress_drops_legacy_hostname():
    mod = _load_server()
    existing = [
        {"hostname": "vllm.chrisvouga.dev", "service": "http://127.0.0.1:8000"},
        {"service": "http_status:404"},
    ]
    merged = mod.merge_tunnel_ingress(
        existing, "llm.chrisvouga.dev", "http://127.0.0.1:8000"
    )
    hostnames = [rule.get("hostname") for rule in merged]
    assert "vllm.chrisvouga.dev" not in hostnames
    assert merged[0]["hostname"] == "llm.chrisvouga.dev"
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
        {"hostname": "llm.chrisvouga.dev", "service": "http://127.0.0.1:8000"},
        {"service": "http_status:404"},
    ]
    resp = {"result": {"config": {"ingress": ingress}}}
    assert mod._tunnel_ingress_from_config_response(resp) == ingress


def test_pid_alive_rejects_invalid_and_zero():
    mod = _load_server()
    assert mod._pid_alive(0) is False
    assert mod._pid_alive(-1) is False
    assert mod._pid_alive(999999999) is False
