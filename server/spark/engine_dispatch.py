"""Route engine operations to Atlas or vLLM."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


def pull_engine_image(cfg: Config, docker_cmd: list) -> None:
    if cfg.engine == "atlas":
        from .engine_atlas import pull_atlas_image

        pull_atlas_image(cfg, docker_cmd)
        return
    from .engine_vllm import pull_vllm_image

    pull_vllm_image(cfg, docker_cmd)


def ensure_engine_model(cfg: Config, docker_cmd: list) -> None:
    if cfg.engine == "atlas":
        from .engine_atlas import ensure_atlas_model

        ensure_atlas_model(cfg, docker_cmd)
        return
    from .engine_vllm import ensure_vllm_model

    ensure_vllm_model(cfg, docker_cmd)


def start_engine(cfg: Config, docker_cmd: list) -> str:
    if cfg.engine == "atlas":
        from .engine_atlas import start_atlas

        return start_atlas(cfg, docker_cmd)
    from .engine_vllm import start_vllm

    return start_vllm(cfg, docker_cmd)


def engine_label(cfg: Config) -> str:
    return "Atlas" if cfg.engine == "atlas" else "vLLM"
