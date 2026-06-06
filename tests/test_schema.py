from local_llm_env.spec_schema import validate_main_spec, validate_models_manifest


def test_validate_main_spec_minimal_valid():
    spec = {
        "host": {},
        "secrets": {
            "provider": "doppler",
            "project": "local-llm",
            "config": "dev",
            "required_keys": ["CF_API_TOKEN"],
        },
        "models": {"manifest_path": "spec/models.yaml", "prune_unmanaged": False},
        "servers": {},
        "services": {},
        "exposure": {"cloudflare": {}},
        "safety": {"cleanup_mode": "managed_only"},
    }
    validated = validate_main_spec(spec)
    assert validated["secrets"]["provider"] == "doppler"


def test_validate_models_manifest_valid():
    manifest = {
        "models": [
            {
                "id": "m1",
                "backend": "llamacpp",
                "source": {"type": "huggingface", "repo": "x/y", "filename": "z.gguf"},
            },
            {
                "id": "m2",
                "backend": "lmstudio",
                "source": {"type": "lmstudio", "catalog_id": "foo/bar"},
            },
        ]
    }
    validated = validate_models_manifest(manifest)
    assert len(validated["models"]) == 2

