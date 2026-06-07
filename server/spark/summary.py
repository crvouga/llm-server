"""The "server is live" summary block printed once boot succeeds."""

import json

from .cloudflare import _cf_public_url
from .compile_cache import _compile_cache_populated
from .console import B, G, X, section, warn
from .models import _model_native_context, _rope_scaling_json


def _context_summary(cfg) -> str:
    kv = "bf16" if cfg.kv_cache_dtype == "auto" else cfg.kv_cache_dtype
    rope = _rope_scaling_json(cfg)
    if rope:
        native = _model_native_context(cfg)
        factor = json.loads(rope)["rope_parameters"]["factor"]
        return (
            f"{cfg.max_model_len} tokens (YaRN {factor}x over {native}, "
            f"KV {kv})"
        )
    return f"{cfg.max_model_len} tokens (KV {kv})"


def _print_atlas_summary(cfg):
    section("🚀 Server is live")
    d = cfg.helper_dir
    spec = (
        f"MTP K={cfg.atlas_num_drafts}" if cfg.atlas_speculative else "off"
    )
    kv = cfg.atlas_kv_cache_dtype
    if cfg.atlas_kv_cache_dtype != "bf16":
        kv += f" (hi-prec layers: {cfg.atlas_kv_high_precision_layers})"
    print(
        f"""
  {B}Engine:{X}   Atlas (Rust/CUDA, GB10/SM121)
  {B}Model:{X}    {cfg.atlas_model}
  {B}Speculative:{X} {spec}  |  {B}Prefix cache:{X} {"on" if cfg.atlas_enable_prefix_caching else "off"}
  {B}GPU budget:{X} {cfg.atlas_gpu_mem_util:.0%}  |  {B}Scheduler:{X} {cfg.atlas_scheduling_policy}
  {B}Context:{X}  {cfg.atlas_max_seq_len} tokens  |  {B}KV cache:{X} {kv}
  {B}Target:{X}   ~130-140 tok/s single-stream (GB10 memory-bandwidth ceiling)
 
  {B}Local API (OpenAI + Anthropic):{X}
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
    {d}/stop.sh          (tunnel only; Atlas stays warm)
    {d}/stop-hard.sh     (stop Atlas + tunnel)
    docker logs -f {cfg.container_name}
"""
    )
    warn(
        "Keep this process running — Ctrl+C or `make server-stop` stops tunnel only "
        "(Atlas stays warm). `make server-stop-hard` stops everything."
    )


def print_summary(cfg, cf_url):
    if cfg.engine == "atlas":
        _print_atlas_summary(cfg)
        return
    section("🚀 Server is live")
    d = cfg.helper_dir
    print(
        f"""
  {B}Model:{X}    {cfg.model}
  {B}DFlash:{X}   {cfg.dflash_drafter} (k={cfg.dflash_num_spec_tokens})
  {B}Profile:{X}  O{cfg.optimization_level} — {cfg.boot_profile or "default"}
  {B}GPU budget:{X} {cfg.gpu_mem_util:.0%}  |  compile cache: {"warm" if _compile_cache_populated(cfg) else "cold"}
  {B}Target:{X}   120-128 tok/s single-stream  |  high aggregate at concurrency {cfg.max_num_seqs}
  {B}Context:{X}  {_context_summary(cfg)}  |  {B}Max seqs:{X} {cfg.max_num_seqs}
 
  {B}Local API:{X}
    http://localhost:{cfg.vllm_port}/v1
 
  {B}Public API (Cloudflare):{X}
    {G}{_cf_public_url(cfg)}/v1{X}
 
  {B}Agent config (local):{X}
    base_url  = http://localhost:{cfg.vllm_port}/v1
    api_key   = not-required
    model     = qwen3.6-35b
 
  {B}Agent config (public):{X}
    base_url  = {_cf_public_url(cfg)}/v1
    api_key   = not-required
    model     = qwen3.6-35b
 
  {B}Commands:{X}
    {d}/status.sh
    {d}/logs.sh
    {d}/stop.sh          (tunnel only; vLLM stays warm)
    {d}/stop-hard.sh     (stop vLLM + tunnel)
    docker logs -f {cfg.container_name}
"""
    )
    warn(
        "Keep this process running — Ctrl+C or `make server-stop` stops tunnel only "
        "(vLLM stays warm). `make server-stop-hard` stops everything."
    )
    warn("First novel request shape takes ~30s for CUDA graph specialisation.")
