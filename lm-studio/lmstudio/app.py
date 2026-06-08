"""Top-level orchestration for the LM Studio Cloudflare tunnel."""

import os
import signal

from spark.cloudflare import (
    _cf_public_url,
    precheck_cf_tunnel,
    resolve_cf_tunnel_token,
    start_cf_tunnel,
)
from spark.console import err, info, ok
from spark.docker_env import ensure_cloudflared
from spark.vault import fetch_vault_secrets
from spark.webapi import CloudflareAPIError

from .config import Config, apply_env_overrides
from .prechecks import run_prechecks
from .runtime import (
    _exit_on_shutdown,
    _handle_sigint,
    _handle_sigterm,
    _request_shutdown,
    _sleep,
    cleanup,
    is_runtime_active,
    is_shutdown_requested,
    register,
)
from .summary import print_summary, write_stop_helper


def main() -> None:
    cfg = Config()
    apply_env_overrides(cfg)
    cfg.vault_token = os.environ.get("VAULT_TOKEN", "")

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        fetch_vault_secrets(cfg)
        _exit_on_shutdown(cfg)

        ensure_cloudflared()
        _exit_on_shutdown(cfg)

        models = run_prechecks(cfg)
        _exit_on_shutdown(cfg)

        tunnel_token = resolve_cf_tunnel_token(cfg)
        _exit_on_shutdown(cfg)

        cf_url = start_cf_tunnel(
            cfg,
            tunnel_token,
            register_proc=register,
            stop_hint="make lm-studio-stop",
        )
        _exit_on_shutdown(cfg)

        cfg.helper_dir.mkdir(parents=True, exist_ok=True)
        (cfg.helper_dir / "tunnel.pid").write_text(str(os.getpid()))
        write_stop_helper(cfg)
        print_summary(cfg, models)

        info(
            f"Running. Ctrl+C or `make lm-studio-stop` stops tunnel ({cf_url})."
        )
        while not is_shutdown_requested():
            if not _sleep(30):
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
        cleanup(cfg)
        raise
    finally:
        if is_shutdown_requested() or is_runtime_active():
            cleanup(cfg)


def stop() -> None:
    """Stop the LM Studio tunnel connector."""
    cfg = Config()
    apply_env_overrides(cfg)
    from spark.cloudflare import stop_tunnel_connector

    stop_tunnel_connector(cfg)
    (cfg.helper_dir / "tunnel.pid").unlink(missing_ok=True)
    ok("LM Studio tunnel stopped")


def setup_tunnel_only() -> None:
    """Configure DNS + ingress without starting the connector."""
    cfg = Config()
    apply_env_overrides(cfg)
    fetch_vault_secrets(cfg)
    ensure_cloudflared()
    precheck_cf_tunnel(cfg)
    resolve_cf_tunnel_token(cfg)
    ok(f"Public API will be at {_cf_public_url(cfg)}/v1 (start with: make lm-studio-tunnel)")


def dispatch(argv: list[str]) -> None:
    arg = argv[0] if argv else ""
    if arg in ("--setup-tunnel", "setup-tunnel"):
        setup_tunnel_only()
    elif arg in ("--stop", "stop"):
        stop()
    else:
        main()
