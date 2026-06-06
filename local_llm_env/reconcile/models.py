from __future__ import annotations

from typing import Any

from ..doppler import doppler_prefix
from ..types import Action, ReconcileResult


def plan_models(spec: dict[str, Any], manifest: dict[str, Any]) -> ReconcileResult:
    component = "models"
    result = ReconcileResult(component=component)

    for model in manifest["models"]:
        model_id = model["id"]
        backend = model["backend"]
        source = model["source"]
        result.observed[f"model:{model_id}:backend"] = backend

        if backend == "lmstudio":
            project = spec["secrets"]["project"]
            config = spec["secrets"]["config"]
            command_prefix = doppler_prefix(project, config)
            catalog_id = source.get("catalog_id")
            if not catalog_id:
                raise ValueError(f"LM Studio model `{model_id}` missing source.catalog_id")
            # We keep this action idempotent by testing before install.
            command = (
                f"{command_prefix}bash -lc "
                f"\"lms ls | rg -q '{catalog_id}' || lms install {catalog_id}\""
            )
            result.actions.append(
                Action(
                    id=f"install-lmstudio-model-{model_id}",
                    component=component,
                    description=f"Ensure LM Studio model `{model_id}` is installed",
                    operation="run_command",
                    payload={"command": command},
                )
            )
            result.managed_resources.append(
                {"type": "model_ref", "backend": "lmstudio", "id": model_id, "catalog_id": catalog_id}
            )
            continue

        raise ValueError(f"Unsupported backend: {backend}")

    return result

