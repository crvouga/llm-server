from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class SpecValidationError(ValueError):
    pass


def _required(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise SpecValidationError(f"Missing required key `{key}` in {ctx}")
    return mapping[key]


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SpecValidationError(f"Spec file does not exist: {path}")
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise SpecValidationError(f"Expected mapping at top-level in {path}")
    return loaded


def validate_main_spec(spec: dict[str, Any]) -> dict[str, Any]:
    host = _required(spec, "host", "spec")
    secrets = _required(spec, "secrets", "spec")
    models = _required(spec, "models", "spec")
    servers = _required(spec, "servers", "spec")
    services = _required(spec, "services", "spec")
    exposure = _required(spec, "exposure", "spec")
    safety = _required(spec, "safety", "spec")

    for name, value in {
        "host": host,
        "secrets": secrets,
        "models": models,
        "servers": servers,
        "services": services,
        "exposure": exposure,
        "safety": safety,
    }.items():
        if not isinstance(value, dict):
            raise SpecValidationError(f"`{name}` must be a mapping")

    if secrets.get("provider") != "doppler":
        raise SpecValidationError("Only `secrets.provider: doppler` is supported")

    _required(secrets, "project", "secrets")
    _required(secrets, "config", "secrets")
    required_keys = _required(secrets, "required_keys", "secrets")
    if not isinstance(required_keys, list) or not all(
        isinstance(k, str) for k in required_keys
    ):
        raise SpecValidationError("`secrets.required_keys` must be a list[str]")

    _required(models, "manifest_path", "models")
    for flag in ("prune_unmanaged",):
        if flag in models and not isinstance(models[flag], bool):
            raise SpecValidationError(f"`models.{flag}` must be boolean")

    if "cloudflare" not in exposure or not isinstance(exposure["cloudflare"], dict):
        raise SpecValidationError("`exposure.cloudflare` must be defined")

    cleanup_mode = safety.get("cleanup_mode", "managed_only")
    if cleanup_mode not in {"managed_only", "full_destroy"}:
        raise SpecValidationError("`safety.cleanup_mode` must be managed_only/full_destroy")

    return spec


def validate_models_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    models = _required(manifest, "models", "models manifest")
    if not isinstance(models, list):
        raise SpecValidationError("`models` must be a list")

    allowed_backends = {"lmstudio"}
    for idx, model in enumerate(models):
        if not isinstance(model, dict):
            raise SpecValidationError(f"models[{idx}] must be a mapping")
        _required(model, "id", f"models[{idx}]")
        backend = _required(model, "backend", f"models[{idx}]")
        if backend not in allowed_backends:
            raise SpecValidationError(
                f"models[{idx}].backend must be one of {sorted(allowed_backends)}"
            )
        source = _required(model, "source", f"models[{idx}]")
        if not isinstance(source, dict):
            raise SpecValidationError(f"models[{idx}].source must be a mapping")
        _required(source, "type", f"models[{idx}].source")

    return manifest

