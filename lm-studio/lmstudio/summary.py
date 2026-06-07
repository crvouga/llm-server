"""Summary printed once the LM Studio tunnel is live."""

from pathlib import Path

from spark.cloudflare import _cf_public_url
from spark.console import B, G, X, section, warn

from .config import Config


def write_stop_helper(cfg: Config) -> None:
    root = Path(__file__).resolve().parent.parent.parent
    stop_sh = cfg.helper_dir / "stop.sh"
    stop_sh.write_text(
        f"#!/usr/bin/env bash\n"
        f'exec python3 "{root}/lm-studio/tunnel" --stop\n'
    )
    stop_sh.chmod(0o755)


def print_summary(cfg: Config, models: list[str]) -> None:
    section("LM Studio tunnel is live")
    d = cfg.helper_dir
    public = _cf_public_url(cfg)
    model_lines = "\n".join(f"    • {m}" for m in models[:8])
    if len(models) > 8:
        model_lines += f"\n    • ... and {len(models) - 8} more"

    print(
        f"""
  {B}Local API:{X}
    http://localhost:{cfg.lm_studio_port}/v1

  {B}Public API (Cloudflare):{X}
    {G}{public}/v1{X}

  {B}Loaded models:{X}
{model_lines}

  {B}Commands:{X}
    {d}/stop.sh              (stop tunnel only)
    make lm-studio-stop
"""
    )
    warn(
        "Keep this process running — Ctrl+C or `make lm-studio-stop` stops the "
        "tunnel only (LM Studio keeps running)."
    )
