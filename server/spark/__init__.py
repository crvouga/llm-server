"""spark — the DGX Spark / GB10 inference server, split into small modules.

Boot order and wiring live in `app.py`. Everything else is a focused module:

    console        coloured output (the universal dependency)
    constants      shared literals, no logic
    config         the Config dataclass + env overrides
    shell/webapi   subprocess + JSON-HTTP helpers
    runtime        process registry, signals, shutdown, cleanup
    docker_env     ensure Docker / cloudflared / git-lfs on the host
    gpu            GPU flags + memory preflight
    containers     generic `docker` container helpers (engine-agnostic)
    compile_cache  vLLM torch/Triton cache (vLLM only)
    models         vLLM model paths + HF downloads (vLLM only)
    doppler        secret fetching
    cloudflare     tunnel API + the cloudflared process
    health         readiness probes + boot wait loop
    engine_atlas   Atlas engine (default)
    engine_vllm    vLLM + DFlash engine (fallback)
    prechecks      fail-fast validation
    helpers        ~/.spark-serve/*.sh scripts
    summary        the "server is live" banner
"""

from .app import dispatch, main

__all__ = ["dispatch", "main"]
