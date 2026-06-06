from __future__ import annotations

from pathlib import Path
from typing import Any

from .doppler import (
    doppler_installed,
    ensure_doppler_access,
    fetch_secrets,
    validate_required_keys,
)
from .reconcile.cloudflare_tunnel import plan_cloudflare, plan_cloudflare_destroy
from .reconcile.dependencies import plan_dependencies
from .reconcile.models import plan_models
from .reconcile.services import plan_services, plan_services_destroy
from .spec_schema import (
    load_yaml_file,
    validate_main_spec,
    validate_models_manifest,
)
from .state import compute_spec_hash
from .types import Action, ReconcilePlan


def load_and_validate_specs(spec_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = validate_main_spec(load_yaml_file(spec_path))
    manifest_path = (spec_path.parent.parent / spec["models"]["manifest_path"]).resolve()
    manifest = validate_models_manifest(load_yaml_file(manifest_path))
    return spec, manifest


def build_plan(spec: dict[str, Any], manifest: dict[str, Any]) -> tuple[ReconcilePlan, dict[str, str]]:
    warnings: list[str] = []
    if not doppler_installed():
        warnings.append(
            "Doppler CLI is not installed. `apply` will fail until dependency reconciliation succeeds."
        )

    secrets: dict[str, str] = {}
    if doppler_installed():
        ensure_doppler_access(spec["secrets"]["project"], spec["secrets"]["config"])
        secrets = fetch_secrets(spec["secrets"]["project"], spec["secrets"]["config"])
        missing = validate_required_keys(secrets, spec["secrets"]["required_keys"])
        if missing:
            raise RuntimeError(
                "Missing required Doppler keys: " + ", ".join(missing)
            )

    results = [
        plan_dependencies(spec),
        plan_models(spec, manifest),
        plan_services(spec, manifest),
        plan_cloudflare(spec, secrets),
    ]
    actions: list[Action] = []
    managed: list[dict[str, Any]] = []
    observed: dict[str, Any] = {}
    for result in results:
        actions.extend(result.actions)
        managed.extend(result.managed_resources)
        observed[result.component] = result.observed

    return (
        ReconcilePlan(
            spec_hash=compute_spec_hash(spec, manifest),
            actions=actions,
            observed=observed,
            managed_resources=managed,
            warnings=warnings,
        ),
        secrets,
    )


def build_destroy_plan(spec: dict[str, Any], state: dict[str, Any]) -> ReconcilePlan:
    results = [
        plan_services_destroy(state),
        plan_cloudflare_destroy(spec, state),
    ]

    if spec["safety"].get("cleanup_mode", "managed_only") == "full_destroy":
        for resource in state.get("managed_resources", []):
            if resource.get("type") in {"model_file", "dir"}:
                results[0].actions.append(
                    Action(
                        id=f"delete-{resource.get('name', Path(resource.get('path', '')).name)}",
                        component="models",
                        description=f"Delete managed resource `{resource.get('path', resource)}`",
                        operation="delete_file",
                        payload={"path": resource["path"]},
                        destructive=True,
                    )
                )

    actions: list[Action] = []
    managed: list[dict[str, Any]] = []
    observed: dict[str, Any] = {}
    for result in results:
        actions.extend(result.actions)
        managed.extend(result.managed_resources)
        observed[result.component] = result.observed

    return ReconcilePlan(
        spec_hash="destroy",
        actions=actions,
        observed=observed,
        managed_resources=managed,
    )

