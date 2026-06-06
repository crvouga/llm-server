from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .types import Action, ReconcilePlan


def compute_spec_hash(spec: dict[str, Any], models_manifest: dict[str, Any]) -> str:
    payload = {"spec": spec, "models_manifest": models_manifest}
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"applied_spec_hash": None, "managed_resources": [], "last_observed": {}}
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"Invalid state file format: {path}")
    return loaded


def save_state(path: Path, plan: ReconcilePlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "applied_spec_hash": plan.spec_hash,
        "managed_resources": plan.managed_resources,
        "last_observed": plan.observed,
    }
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def action_to_dict(action: Action) -> dict[str, Any]:
    return asdict(action)


def diff_state(previous: dict[str, Any], current_plan: ReconcilePlan) -> dict[str, Any]:
    prev_hash = previous.get("applied_spec_hash")
    prev_managed = {
        json.dumps(item, sort_keys=True) for item in previous.get("managed_resources", [])
    }
    new_managed = {json.dumps(item, sort_keys=True) for item in current_plan.managed_resources}
    added = [json.loads(item) for item in sorted(new_managed - prev_managed)]
    removed = [json.loads(item) for item in sorted(prev_managed - new_managed)]

    return {
        "spec_changed": prev_hash != current_plan.spec_hash,
        "actions_count": len(current_plan.actions),
        "resources_added": added,
        "resources_removed": removed,
    }

