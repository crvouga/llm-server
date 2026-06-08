"""The "server is live" summary block printed once boot succeeds."""

from .cloudflare import _cf_public_url
from .console import B, G, X, section, warn


def print_summary(cfg, cf_url):
    section("🚀 Server is live")
    d = cfg.helper_dir
    spec = (
        f"MTP K={cfg.atlas_num_drafts}" if cfg.atlas_speculative else "off"
    )
    kv = cfg.atlas_kv_cache_dtype
    if cfg.atlas_kv_cache_dtype != "bf16":
        kv += " (hi-prec layers: auto)"
    print(
        f"""
  {B}Engine:{X}   Atlas (Rust/CUDA, GB10/SM121)
  {B}Model:{X}    {cfg.atlas_model}
  {B}Speculative:{X} {spec}  |  {B}Prefix cache:{X} on
  {B}GPU budget:{X} {cfg.atlas_gpu_mem_util:.0%}  |  {B}Scheduler:{X} slai
  {B}Context:{X}  {cfg.atlas_max_seq_len} tokens  |  {B}KV cache:{X} {kv}
  {B}Target:{X}   ~80+ tok/s single-stream (Qwen3-Coder-Next on GB10)

  {B}Local API (OpenAI-compatible):{X}
    http://localhost:{cfg.atlas_port}/v1

  {B}Public API (Cloudflare):{X}
    {G}{_cf_public_url(cfg)}/v1{X}

  {B}Agent config (public):{X}
    base_url  = {_cf_public_url(cfg)}/v1
    api_key   = not-required
    model     = atlas

  {B}Commands:{X}
    {d}/status.sh
    {d}/logs.sh
    {d}/stop.sh          (stop Atlas + tunnel)
    docker logs -f {cfg.container_name}
"""
    )
    warn(
        "Keep this process running — Ctrl+C or `make server-stop` stops Atlas + tunnel."
    )
