"""Process registry, signal handling, and tunnel-only cleanup."""

import os
import sys
import time

from spark.cloudflare import stop_tunnel_connector
from spark.console import B, X, Y, ok
from spark.runtime import _kill_pid

from .config import Config

_managed: list = []
_shutdown_requested = False
_cleanup_done = False
_runtime_active = False


def is_shutdown_requested() -> bool:
    return _shutdown_requested


def is_runtime_active() -> bool:
    return _runtime_active


def register(proc):
    global _runtime_active
    _runtime_active = True
    _managed.append(proc)
    return proc


def _request_shutdown(*, force: bool = False) -> None:
    global _shutdown_requested
    if force or _shutdown_requested:
        print(f"\n{Y}[!]{X} Force quit", flush=True)
        os._exit(130)
    _shutdown_requested = True
    print(
        f"\n{Y}[!]{X} Shutting down... (Ctrl+C again to force quit)",
        flush=True,
    )


def _handle_sigint(signum, frame):
    _request_shutdown()


def _handle_sigterm(signum, frame):
    _request_shutdown()


def _sleep(seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _shutdown_requested:
            return False
        time.sleep(min(0.2, end - time.monotonic()))
    return True


def _exit_on_shutdown(cfg: Config) -> None:
    if _shutdown_requested:
        cleanup(cfg)
        sys.exit(130)


def cleanup(cfg: Config) -> None:
    global _cleanup_done, _runtime_active
    if _cleanup_done:
        return
    _cleanup_done = True
    print(f"\n{B}━━━  Shutting down  ━━━{X}", flush=True)
    stop_tunnel_connector(cfg, managed_procs=_managed)
    for proc in _managed:
        if proc.poll() is None:
            _kill_pid(proc.pid, f"process {proc.pid}")
    (cfg.helper_dir / "tunnel.pid").unlink(missing_ok=True)
    _runtime_active = False
    ok("Clean shutdown complete (tunnel stopped).")
