from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Action:
    id: str
    component: str
    description: str
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
    destructive: bool = False


@dataclass(slots=True)
class ReconcileResult:
    component: str
    actions: list[Action] = field(default_factory=list)
    observed: dict[str, Any] = field(default_factory=dict)
    managed_resources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ReconcilePlan:
    spec_hash: str
    actions: list[Action]
    observed: dict[str, Any]
    managed_resources: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

