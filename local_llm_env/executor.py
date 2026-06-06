from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .types import Action


class ActionExecutionError(RuntimeError):
    pass


def execute_action(action: Action, env: dict[str, str] | None = None) -> None:
    if action.operation == "run_command":
        run_command(action.payload["command"], env=env)
        return
    if action.operation == "write_file":
        path = Path(action.payload["path"]).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(action.payload["content"])
        return
    if action.operation == "delete_file":
        path = Path(action.payload["path"]).expanduser()
        if path.exists():
            path.unlink()
        return
    if action.operation == "mkdir":
        path = Path(action.payload["path"]).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return
    raise ActionExecutionError(f"Unsupported action operation: {action.operation}")


def run_command(command: str, env: dict[str, str] | None = None) -> None:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        command,
        shell=True,
        env=merged_env,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ActionExecutionError(
            f"Command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def format_action(action: Action) -> str:
    prefix = "!" if action.destructive else "+"
    return f"{prefix} [{action.component}] {action.description}"


def summarize_actions(actions: list[Action]) -> dict[str, Any]:
    destructive = sum(1 for item in actions if item.destructive)
    return {
        "total": len(actions),
        "destructive": destructive,
        "non_destructive": len(actions) - destructive,
    }

