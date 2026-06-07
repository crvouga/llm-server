"""Process registry, signal handling, graceful shutdown + cleanup.

Owns all shared mutable runtime state. Other modules must touch shutdown/active
state through the accessor functions here (never by importing the booleans), so
reassignment stays visible across modules.
"""

import os
import signal
import subprocess
import sys
import time

from .config import _should_remove_container, engine_label
from .console import B, X, Y, info, ok
from .containers import _container_status

_managed: list = []
_managed_containers: list = []
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


def register_container(name):
    global _runtime_active
    _runtime_active = True
    _managed_containers.append(name)


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
    """Sleep in short chunks so Ctrl+C is felt within ~200ms. Returns False if interrupted."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _shutdown_requested:
            return False
        time.sleep(min(0.2, end - time.monotonic()))
    return True


def _exit_on_shutdown(cfg) -> None:
    if _shutdown_requested:
        cleanup(cfg, stop_vllm=True)
        sys.exit(130)


def _kill_pid(pid: int, label: str, timeout: float = 5) -> None:
    try:
        os.kill(pid, 0)
    except OSError:
        return
    info(f"Stopping {label} (PID {pid})...")
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _stop_spark_tunnel(cfg):
    """Stop the vLLM tunnel started by this server (never touches lm-studio)."""
    pid_file = cfg.helper_dir / "cloudflared.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            _kill_pid(pid, "Cloudflare tunnel")
        except (OSError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)

    for proc in list(_managed):
        if proc.poll() is not None:
            continue
        try:
            with open(f"/proc/{proc.pid}/cmdline", "rb") as fh:
                if b"cloudflared" in fh.read():
                    _kill_pid(proc.pid, "Cloudflare tunnel")
        except OSError:
            pass


def cleanup(cfg, *, stop_vllm: bool = False):
    global _cleanup_done, _runtime_active
    if _cleanup_done:
        return
    _cleanup_done = True
    print(f"\n{B}━━━  Shutting down  ━━━{X}", flush=True)
    _stop_spark_tunnel(cfg)
    for proc in _managed:
        if proc.poll() is None:
            _kill_pid(proc.pid, f"process {proc.pid}")
    if stop_vllm:
        for name in _managed_containers:
            info(f"Stopping container '{name}'...")
            subprocess.run(
                [*cfg.docker_cmd, "stop", name], capture_output=True, timeout=30
            )
            if _should_remove_container(cfg):
                subprocess.run(
                    [*cfg.docker_cmd, "rm", name], capture_output=True, timeout=30
                )
    elif _managed_containers or _container_status(cfg) == "running":
        names = _managed_containers or [cfg.container_name]
        ok(f"Leaving {engine_label(cfg)} container running: {', '.join(names)}")
    (cfg.helper_dir / "server.pid").unlink(missing_ok=True)
    _runtime_active = False
    if stop_vllm:
        ok(f"Clean shutdown complete ({engine_label(cfg)} + tunnel stopped).")
    else:
        ok(f"Clean shutdown complete (tunnel stopped; {engine_label(cfg)} container left running).")
