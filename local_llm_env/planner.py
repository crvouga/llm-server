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
from .spec_schema import load_yaml_file, validate_main_spec
from .state import compute_spec_hash
from .types import Action, ReconcilePlan


def load_and_validate_specs(spec_path: Path) -> dict[str, Any]:
    spec = validate_main_spec(load_yaml_file(spec_path))
    return spec


def build_plan(spec: dict[str, Any], rotate_tunnel: bool = False) -> tuple[ReconcilePlan, dict[str, str]]:
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
        plan_cloudflare(spec, secrets, rotate_tunnel=rotate_tunnel),
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
            spec_hash=compute_spec_hash(spec),
            actions=actions,
            observed=observed,
            managed_resources=managed,
            warnings=warnings,
        ),
        secrets,
    )


def build_destroy_plan(spec: dict[str, Any], state: dict[str, Any]) -> ReconcilePlan:
    results = [
        plan_cloudflare_destroy(spec, state),
    ]

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

