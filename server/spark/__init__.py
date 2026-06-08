"""spark — Atlas inference server for ASUS Ascent GX10 / DGX Spark / GB10.

Boot order and wiring live in `app.py`. Everything else is a focused module:

    console        coloured output
    config         Config dataclass + env overrides
    shell/webapi   subprocess + JSON-HTTP helpers
    runtime        process registry, signals, shutdown
    docker_env     ensure Docker / cloudflared on the host
    gpu            GPU flags + preflight
    containers     Docker container helpers
    doppler        secret fetching
    cloudflare     tunnel API + cloudflared process
    health         readiness probes + boot wait loop
    engine_atlas   Atlas container launch
    prechecks      fail-fast validation
    helpers        ~/.spark-serve/*.sh scripts
    summary        the "server is live" banner
"""

from .app import dispatch, main

__all__ = ["dispatch", "main"]
