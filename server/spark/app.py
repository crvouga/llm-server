"""Top-level orchestration: boot the engine + tunnel, run the watchdog, handle
the CLI subcommands (stop / stop-hard / setup-tunnel / clear-compile-cache).

This is the only module that wires everything together. Read this first to
understand the boot order; each step lives in its own focused module.
"""

import os
import platform
import signal
import subprocess

from . import runtime
from .cloudflare import (
    _cf_public_url,
    precheck_cf_tunnel,
    resolve_cf_tunnel_token,
    start_cf_tunnel,
)
from .compile_cache import (
    _clear_compile_cache,
    _ensure_compile_cache,
    _prepare_compile_cache_dir,
    _resolve_optimization_profile,
)
from .config import Config, _apply_env_overrides, engine_label
from .console import die, err, info, ok, section, warn
from .containers import _container_logs_tail, _container_status
from .docker_env import (
    _resolve_docker_cmd,
    ensure_cloudflared,
    ensure_docker,
    ensure_git_lfs,
)
from .doppler import fetch_doppler_secrets
from .engine_atlas import ensure_atlas_model, pull_atlas_image, start_atlas
from .engine_vllm import pull_vllm_image, start_vllm, warmup_vllm
from .health import _gpu_oom_hint, wait_for_vllm
from .helpers import write_helpers
from .models import _resolve_model_dir, ensure_models
from .prechecks import run_prechecks
from .runtime import (
    _exit_on_shutdown,
    _handle_sigint,
    _handle_sigterm,
    _request_shutdown,
    cleanup,
    register_container,
)
from .summary import print_summary
from .webapi import CloudflareAPIError


def _boot_engine(cfg, docker_cmd) -> str:
    """Start the selected engine, wait for readiness, warm up (vLLM only)."""
    if cfg.engine == "atlas":
        boot_mode = start_atlas(cfg, docker_cmd)
        if boot_mode != "ready":
            wait_for_vllm(cfg)
        return boot_mode
    boot_mode = start_vllm(cfg, docker_cmd)
    if boot_mode != "ready":
        wait_for_vllm(cfg)
        warmup_vllm(cfg)
    return boot_mode


def main():
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    cfg.doppler_token = os.environ.get("DOPPLER_TOKEN", "")

    if platform.machine() != "aarch64":
        warn(
            f"Expected aarch64 (GB10), got {platform.machine()} — optimisations may not apply"
        )

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        fetch_doppler_secrets(cfg)
        _exit_on_shutdown(cfg)

        docker_cmd = ensure_docker(cfg)
        _exit_on_shutdown(cfg)
        ensure_cloudflared()
        if cfg.engine != "atlas":
            ensure_git_lfs()
        run_prechecks(cfg, docker_cmd)
        _exit_on_shutdown(cfg)

        if cfg.engine == "atlas":
            pull_atlas_image(cfg, docker_cmd)
            _exit_on_shutdown(cfg)
            ensure_atlas_model(cfg, docker_cmd)
            _exit_on_shutdown(cfg)
            _boot_engine(cfg, docker_cmd)
        else:
            _ensure_compile_cache(cfg, docker_cmd)
            _exit_on_shutdown(cfg)
            _resolve_optimization_profile(cfg)
            pull_vllm_image(cfg, docker_cmd)
            _exit_on_shutdown(cfg)
            ensure_models(cfg, docker_cmd)
            _boot_engine(cfg, docker_cmd)
        _exit_on_shutdown(cfg)

        tunnel_token = resolve_cf_tunnel_token(cfg)
        _exit_on_shutdown(cfg)
        cf_url = start_cf_tunnel(cfg, tunnel_token)

        write_helpers(cfg)
        (cfg.helper_dir / "server.pid").write_text(str(os.getpid()))
        print_summary(cfg, cf_url)

        info(
            f"Running. Ctrl+C or `make server-stop` stops tunnel ({engine_label(cfg)} stays warm). "
            "`make server-stop-hard` stops everything."
        )
        while not runtime.is_shutdown_requested():
            # Watchdog: restart container if it exits unexpectedly
            r = subprocess.run(
                [
                    *docker_cmd,
                    "inspect",
                    "--format",
                    "{{.State.Status}}",
                    cfg.container_name,
                ],
                capture_output=True,
                text=True,
            )
            if r.stdout.strip() not in ("running", ""):
                logs = _container_logs_tail(cfg, lines=80)
                oom_hint = _gpu_oom_hint(logs)
                if oom_hint:
                    die(
                        f"Container '{cfg.container_name}' exited (likely GPU memory)."
                        f"{oom_hint}\nRecent logs:\n{logs}"
                    )
                warn("Container exited unexpectedly — restarting...")
                _boot_engine(cfg, docker_cmd)
            if not runtime._sleep(30):
                break

    except KeyboardInterrupt:
        _request_shutdown()
    except SystemExit:
        raise
    except CloudflareAPIError as e:
        err(f"Cloudflare API error: HTTP {e.code}: {e.message}")
        if e.body:
            err(e.body[:500])
        raise SystemExit(1) from e
    except Exception as e:
        err(f"Unexpected error: {e}")
        cleanup(cfg, stop_vllm=False)
        if _container_status(cfg) == "running":
            label = "Atlas" if cfg.engine == "atlas" else "vLLM"
            warn(f"{label} container still running — use: make server-stop-hard")
        raise
    finally:
        if runtime.is_shutdown_requested() or runtime.is_runtime_active():
            cleanup(cfg, stop_vllm=False)


def stop_soft():
    """Stop tunnel + launcher; leave the engine container running for fast restart."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    cfg.docker_cmd = _resolve_docker_cmd() or ["docker"]
    cleanup(cfg, stop_vllm=False)


def stop_hard():
    """Stop tunnel, launcher, and the engine container."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    cfg.docker_cmd = _resolve_docker_cmd() or ["docker"]
    register_container(cfg.container_name)
    cleanup(cfg, stop_vllm=True)


def setup_tunnel_only():
    """Configure DNS + ingress for the engine without starting the server."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    fetch_doppler_secrets(cfg)
    ensure_cloudflared()
    precheck_cf_tunnel(cfg)
    resolve_cf_tunnel_token(cfg)
    ok(f"Public API will be at {_cf_public_url(cfg)}/v1 (start with: make run)")


def clear_compile_cache_only():
    """Remove vLLM torch/Triton compile artifacts (forces a cold recompile)."""
    cfg = Config()
    cfg.model_dir = _resolve_model_dir()
    _apply_env_overrides(cfg)
    cfg.docker_cmd = _resolve_docker_cmd() or ["docker"]
    section("Clearing compile cache")
    _prepare_compile_cache_dir(cfg, cfg.docker_cmd)
    _clear_compile_cache(cfg)


def dispatch(argv):
    """Route CLI args to a subcommand (default: run the server)."""
    arg = argv[0] if argv else ""
    if arg in ("--setup-tunnel", "setup-tunnel"):
        setup_tunnel_only()
    elif arg in ("--stop", "stop"):
        stop_soft()
    elif arg in ("--stop-hard", "stop-hard"):
        stop_hard()
    elif arg in ("--clear-compile-cache", "clear-compile-cache"):
        clear_compile_cache_only()
    else:
        main()
