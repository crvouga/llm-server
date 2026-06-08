"""Top-level orchestration: boot Atlas + tunnel, run the watchdog, handle CLI."""

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
from .config import Config, _apply_env_overrides
from .console import die, err, info, ok, warn
from .containers import _container_logs_tail
from .docker_env import _resolve_docker_cmd, ensure_cloudflared, ensure_docker
from .doppler import fetch_doppler_secrets
from .engine_atlas import ensure_atlas_model, pull_atlas_image, start_atlas
from .health import _gpu_oom_hint, wait_for_engine
from .helpers import write_helpers
from .prechecks import run_prechecks
from .runtime import (
    _exit_on_shutdown,
    _handle_sigint,
    _handle_sigterm,
    _request_shutdown,
    cleanup,
    load_runtime_state,
    register_container,
)
from .summary import print_summary
from .webapi import CloudflareAPIError


def main():
    cfg = Config()
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
        run_prechecks(cfg, docker_cmd)
        _exit_on_shutdown(cfg)

        pull_atlas_image(cfg, docker_cmd)
        _exit_on_shutdown(cfg)
        ensure_atlas_model(cfg, docker_cmd)
        _exit_on_shutdown(cfg)

        boot_mode = start_atlas(cfg, docker_cmd)
        if boot_mode != "ready":
            wait_for_engine(cfg)
        _exit_on_shutdown(cfg)

        tunnel_token = resolve_cf_tunnel_token(cfg)
        _exit_on_shutdown(cfg)
        cf_url = start_cf_tunnel(
            cfg, tunnel_token, register_proc=runtime.register
        )

        write_helpers(cfg)
        (cfg.helper_dir / "server.pid").write_text(str(os.getpid()))
        print_summary(cfg, cf_url)

        info(
            "Running. Ctrl+C or `make server-stop` stops tunnel + Atlas container."
        )
        while not runtime.is_shutdown_requested():
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
                boot_mode = start_atlas(cfg, docker_cmd)
                if boot_mode != "ready":
                    wait_for_engine(cfg)
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
        cleanup(cfg, stop_engine=True)
        raise
    finally:
        if runtime.is_shutdown_requested() or runtime.is_runtime_active():
            cleanup(cfg, stop_engine=True)


def stop():
    """Stop tunnel, launcher, and the Atlas container."""
    cfg = Config()
    _apply_env_overrides(cfg)
    if not load_runtime_state(cfg):
        cfg.docker_cmd = _resolve_docker_cmd() or ["docker"]
    register_container(cfg.container_name)
    cleanup(cfg, stop_engine=True)


def setup_tunnel_only():
    """Configure DNS + ingress for Atlas without starting the server."""
    cfg = Config()
    _apply_env_overrides(cfg)
    fetch_doppler_secrets(cfg)
    ensure_cloudflared()
    precheck_cf_tunnel(cfg)
    resolve_cf_tunnel_token(cfg)
    ok(f"Public API will be at {_cf_public_url(cfg)}/v1 (start with: make run)")


def dispatch(argv):
    """Route CLI args to a subcommand (default: run the server)."""
    arg = argv[0] if argv else ""
    if arg in ("--setup-tunnel", "setup-tunnel"):
        setup_tunnel_only()
    elif arg in ("--stop", "stop"):
        stop()
    else:
        main()
