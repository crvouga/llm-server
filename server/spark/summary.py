"""The "server is live" summary block printed once boot succeeds."""

from .cloudflare import _cf_public_url
from .console import B, G, X, section, warn
from .engine_dispatch import engine_label
from .engine_vllm import _vllm_speculative_label


def _spec_line(cfg) -> str:
    if cfg.engine == "atlas":
        return (
            f"MTP K={cfg.atlas_num_drafts}"
            if cfg.atlas_speculative
            else "off"
        )
    label = _vllm_speculative_label(cfg)
    return "off" if label == "no speculative" else label


def _model_line(cfg) -> str:
    return cfg.atlas_model if cfg.engine == "atlas" else cfg.vllm_model


def _context_line(cfg) -> tuple[int, str, float]:
    if cfg.engine == "atlas":
        kv = cfg.atlas_kv_cache_dtype
        if cfg.atlas_kv_cache_dtype != "bf16":
            kv += " (hi-prec layers: auto)"
        return cfg.atlas_max_seq_len, kv, cfg.atlas_gpu_mem_util
    return cfg.vllm_max_model_len, cfg.vllm_kv_cache_dtype, cfg.vllm_gpu_mem_util


def print_summary(cfg, cf_url):
    section("🚀 Server is live")
    d = cfg.helper_dir
    label = engine_label(cfg)
    spec = _spec_line(cfg)
    model = _model_line(cfg)
    context, kv, gpu_budget = _context_line(cfg)
    if cfg.engine == "atlas":
        engine_desc = "Atlas (Rust/CUDA, GB10/SM121)"
        target = "~120-145 tok/s single-stream, sub-second TTFT (non-thinking)"
        scheduler = f"  {B}Scheduler:{X} slai\n"
    else:
        engine_desc = "vLLM (NVIDIA, GB10/SM121)"
        target = "~88-108 tok/s with DFlash, sub-second TTFT"
        scheduler = ""
    print(
        f"""
  {B}Engine:{X}   {engine_desc}
  {B}Model:{X}    {model}
  {B}Speculative:{X} {spec}  |  {B}Prefix cache:{X} on
  {B}GPU budget:{X} {gpu_budget:.0%}{scheduler}  {B}Context:{X}  {context} tokens  |  {B}KV cache:{X} {kv}
  {B}Thinking:{X} off by default (proxy injects opt-out; clients can opt in)
  {B}Target:{X}   {target}

  {B}Local API (OpenAI-compatible):{X}
    http://localhost:{cfg.service_port}/v1

  {B}Public API (Cloudflare):{X}
    {G}{_cf_public_url(cfg)}/v1{X}

  {B}Agent config (public):{X}
    base_url  = {_cf_public_url(cfg)}/v1
    api_key   = not-required
    model     = {cfg.vllm_served_model_name if cfg.engine == "vllm" else "atlas"}

  {B}Commands:{X}
    {d}/status.sh
    {d}/logs.sh
    {d}/stop.sh          (stop {label} + tunnel)
    docker logs -f {cfg.container_name}
"""
    )
    warn(
        f"Keep this process running — Ctrl+C or `make server-stop` stops "
        f"{label} + tunnel."
    )
