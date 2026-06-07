"""Fail-fast prechecks before starting the LM Studio tunnel."""

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from spark.cloudflare import precheck_cf_tunnel
from spark.console import die, ok, section

from .config import Config


def _lms_hint() -> str:
    lms = Path.home() / ".lmstudio" / "bin" / "lms"
    if lms.is_file():
        return f"\n  Or run: {lms} server start"
    return ""


def precheck_lm_studio(cfg: Config) -> list[str]:
    """Return loaded model ids from the local LM Studio server."""
    section("Precheck: LM Studio")
    url = f"http://127.0.0.1:{cfg.lm_studio_port}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                die(
                    f"LM Studio not ready at {url} (HTTP {resp.status}).\n"
                    "  Start LM Studio and enable the local server "
                    f"(default port {cfg.lm_studio_port})."
                    + _lms_hint()
                )
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        die(
            f"LM Studio not reachable at http://127.0.0.1:{cfg.lm_studio_port}.\n"
            f"  {e.reason}\n"
            "  Start LM Studio and enable the local server "
            f"(default port {cfg.lm_studio_port})."
            + _lms_hint()
        )
    except json.JSONDecodeError as e:
        die(f"LM Studio returned invalid JSON from /v1/models: {e}")

    models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    if not models:
        die(
            f"LM Studio is listening on port {cfg.lm_studio_port} but no models are loaded.\n"
            "  Load a model in LM Studio before starting the tunnel."
        )
    ok(f"LM Studio ready on port {cfg.lm_studio_port} ({len(models)} model(s))")
    return models


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _spark_server_running() -> bool:
    spark_pid = Path.home() / ".spark-serve" / "server.pid"
    if spark_pid.exists():
        try:
            if _pid_alive(int(spark_pid.read_text().strip())):
                return True
        except (OSError, ValueError):
            pass

    r = subprocess.run(
        ["pgrep", "-f", r"python3 .*/server/server\.py"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return False

    for pid in r.stdout.split():
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().decode(errors="replace")
        except OSError:
            continue
        if "--stop" in cmd or "--setup-tunnel" in cmd or "--clear-compile-cache" in cmd:
            continue
        return True
    return False


def precheck_no_spark_conflict(cfg: Config) -> None:
    section("Precheck: server conflict")
    if not _spark_server_running():
        ok("LLM server is not running")
        return
    die(
        "The Atlas/vLLM server is already running.\n"
        "  Stop it first (`make server-stop`) — both use "
        f"{cfg.cf_tunnel_hostname}."
    )


def run_prechecks(cfg: Config) -> list[str]:
    section("Running prechecks (fail fast)")
    precheck_cf_tunnel(cfg)
    models = precheck_lm_studio(cfg)
    precheck_no_spark_conflict(cfg)
    ok("All prechecks passed — starting tunnel")
    return models
