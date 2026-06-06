from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..doppler import doppler_prefix
from ..types import Action, ReconcileResult


def plan_models(spec: dict[str, Any], manifest: dict[str, Any]) -> ReconcileResult:
    models_spec = spec["models"]
    component = "models"
    result = ReconcileResult(component=component)

    download_dir = Path(models_spec.get("download_dir", "~/.local/share/local-llm-models")).expanduser()
    if not download_dir.exists():
        result.actions.append(
            Action(
                id="create-model-download-dir",
                component=component,
                description=f"Create model directory `{download_dir}`",
                operation="mkdir",
                payload={"path": str(download_dir)},
            )
        )
    result.managed_resources.append({"type": "dir", "name": "models_download_dir", "path": str(download_dir)})

    managed_local_files: set[str] = set()
    for model in manifest["models"]:
        model_id = model["id"]
        backend = model["backend"]
        source = model["source"]
        result.observed[f"model:{model_id}:backend"] = backend

        if backend == "llamacpp":
            file_name = model.get("local_path", f"{model_id}.gguf")
            local_path = download_dir / file_name
            managed_local_files.add(str(local_path))
            if not local_path.exists():
                result.actions.append(
                    Action(
                        id=f"download-{model_id}",
                        component=component,
                        description=f"Download llama.cpp model `{model_id}`",
                        operation="run_command",
                        payload={"command": build_llamacpp_download_command(source, local_path)},
                    )
                )
            result.managed_resources.append(
                {"type": "model_file", "backend": "llamacpp", "id": model_id, "path": str(local_path)}
            )
            continue

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

    if models_spec.get("prune_unmanaged"):
        existing = list_existing_model_files(download_dir)
        unmanaged = sorted(set(existing) - managed_local_files)
        for path in unmanaged:
            result.actions.append(
                Action(
                    id=f"prune-unmanaged-model-{Path(path).name}",
                    component=component,
                    description=f"Remove unmanaged model file `{path}`",
                    operation="delete_file",
                    payload={"path": path},
                    destructive=True,
                )
            )

    return result


def build_llamacpp_download_command(source: dict[str, Any], local_path: Path) -> str:
    src_type = source.get("type")
    if src_type == "huggingface":
        repo = source["repo"]
        filename = source["filename"]
        return (
            "mkdir -p \"$(dirname "
            f"'{local_path}'"
            ")\" && "
            "huggingface-cli download "
            f"{repo} {filename} --local-dir \"{local_path.parent}\" "
            f"--local-dir-use-symlinks False && mv \"{local_path.parent / filename}\" \"{local_path}\""
        )
    if src_type == "http":
        url = source["url"]
        return (
            "mkdir -p \"$(dirname "
            f"'{local_path}'"
            ")\" && "
            f"curl -L \"{url}\" -o \"{local_path}\""
        )
    raise ValueError(f"Unsupported llama.cpp model source.type: {src_type}")


def list_existing_model_files(path: Path) -> list[str]:
    if not path.exists():
        return []
    files: list[str] = []
    for root, _, names in os.walk(path):
        for name in names:
            files.append(str(Path(root) / name))
    return files

