from local_llm_env.spec_schema import validate_main_spec


def test_validate_main_spec_minimal_valid():
    spec = {
        "host": {},
        "secrets": {
            "provider": "doppler",
            "project": "local-llm",
            "config": "dev",
            "required_keys": ["CF_API_TOKEN"],
        },
        "services": {},
        "exposure": {"cloudflare": {}},
        "safety": {"cleanup_mode": "managed_only"},
    }
    validated = validate_main_spec(spec)
    assert validated["secrets"]["provider"] == "doppler"

