"""The Config dataclass + env overrides + a couple of pure config helpers."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from .constants import _SERVED_MODEL


# ── Config ────────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # Doppler
    doppler_token: str = ""
    doppler_project: str = "personal"
    doppler_config: str = "dev"

    # Secrets — populated from Doppler
    cf_api_token: str = ""
    cf_account_id: str = ""
    cf_tunnel_token: str = ""
    hf_token: str = ""

    # Cloudflare tunnel — connector token fetched via CLOUDFLARE_API_TOKEN at runtime
    cf_tunnel_name: str = "llm"
    cf_tunnel_hostname: str = "llm.chrisvouga.dev"

    # Models
    # Main:    AEON-7 heretic-NVFP4 — production-stable, correct vLLM key layout
    # Drafter: z-lab DFlash block-diffusion (must be post 2026-04-19 revision)
    # Flat layout under {model_dir}/{main,drafter} — predictable for vLLM flags
    model: str = "AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4"
    dflash_drafter: str = "z-lab/Qwen3.6-35B-A3B-DFlash"
    model_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "qwen36")

    # vLLM
    # Image: SM121-patched (8 patches, FlashInfer 0.6.8, Marlin GEMM enforcement)
    # ⚠️  max_num_seqs > 16 causes system freeze during torch.compile on GB10
    vllm_port: int = 8000
    # 64K (YaRN 2x over 32K native) maximizes parallel-agent KV headroom: at 256K
    # only ~5 agents fit; at 64K the max_num_seqs=16 ceiling becomes the limit
    # instead. Raise with VLLM_MAX_MODEL_LEN=262144 for long single-agent sessions.
    max_model_len: int = 65536
    # "auto" (bf16) KV cache — the flash_attn backend on this SM121 build rejects
    # fp8 ("kv_cache_dtype not supported"), and 64K bf16 KV fits in 128GB anyway.
    # Override with VLLM_KV_CACHE_DTYPE=fp8 only if also switching attention backend.
    kv_cache_dtype: str = "auto"
    rope_scaling_enabled: bool = True
    native_context_len: int = 0  # 0 = auto-detect from model config.json
    # flash_attn handles both the main model (causal) and the DFlash drafter /
    # vision encoder (non-causal). flashinfer raises "non-causal attention not
    # supported" for the diffusion drafter, so do not switch without testing.
    attention_backend: str = "flash_attn"
    gpu_mem_util: float = 0.85
    max_num_seqs: int = 16  # hard ceiling on GB10
    max_batched_tokens: int = 16384
    # k=8 balances single-stream speed vs parallel-agent throughput: per-position
    # draft acceptance falls below ~5% past position 6, so k=15 mostly wastes
    # verify compute under concurrency (the 50 tok/s dips). Tune with VLLM_DFLASH_K
    # (e.g. 15 for pure single-agent, 4 for heavy concurrency).
    dflash_num_spec_tokens: int = 8
    # vLLM defaults capture CUDA graphs up to 512 batch slots; we only run 16 seqs.
    max_cudagraph_capture_size: int = 16
    # 0=eager (~1-2 min), 1=balanced (default), 2=production. VLLM_PRODUCTION=1 for O2.
    optimization_level: int = 1
    # Experimental: route NVFP4 MoE experts through FlashInfer instead of the
    # default Marlin kernel (Marlin is compute-bound and slow when batched). The
    # runtime auto-rejected FlashInfer on sm_121 in testing, so this is opt-in via
    # VLLM_FLASHINFER_MOE_FP4=1 (backend: "throughput" or "latency"). If the
    # kernels reject the device the container crash-loops and the watchdog reports it.
    flashinfer_moe_fp4: bool = False
    flashinfer_moe_backend: str = "throughput"
    container_name: str = "vllm-qwen36-dflash"
    vllm_image: str = "ghcr.io/aeon-7/vllm-spark-omni-q36:v1.2"
    compile_cache_dir: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "vllm-spark-compile"
    )
    docker_cmd: list = field(default_factory=lambda: ["docker"])
    gpu_exclusive: bool = True
    boot_profile: str = ""

    # ── Engine selection ────────────────────────────────────────────────────────
    # "atlas" (default) — Atlas, a Rust/CUDA engine purpose-built for GB10/SM121:
    #   native fp8/nvfp4 KV cache, MTP speculative decoding, <2 min cold start, and
    #   an OpenAI + Anthropic API. "vllm" — the legacy vLLM + DFlash path (fallback).
    # Override with ENGINE=vllm (or LLM_ENGINE=vllm).
    engine: str = "atlas"

    # ── Atlas engine ──────────────────────────────────────────────────────────────
    # One multi-model binary; the right hand-tuned kernels are picked from the
    # model's config.json at startup. The checkpoint must be pre-downloaded into the
    # mounted HF hub cache (server does this automatically before launch).
    atlas_image: str = "avarok/atlas-gb10:latest"
    atlas_model: str = "Qwen/Qwen3.6-35B-A3B-FP8"
    atlas_container: str = "atlas"
    atlas_port: int = 8888
    # 128K default. fp8 KV keeps this affordable; nvfp4/turbo4 (4x compression) or
    # NVMe High-Speed-Swap push to 256K. Override with ATLAS_MAX_SEQ_LEN.
    atlas_max_seq_len: int = 131072
    # KV cache dtype: bf16 | fp8 (default) | turbo8 | nvfp4 | turbo4 | turbo3.
    atlas_kv_cache_dtype: str = "fp8"
    # "auto" keeps boundary attention layers at BF16 where routing is most sensitive.
    atlas_kv_high_precision_layers: str = "auto"
    # MTP (Multi-Token Prediction) speculative decoding; K = drafts per step.
    atlas_speculative: bool = True
    atlas_num_drafts: int = 2
    # SLAi scheduler keeps MTP verify batches dense.
    atlas_scheduling_policy: str = "slai"
    atlas_enable_prefix_caching: bool = True
    atlas_tool_call_parser: str = "qwen3_coder"
    atlas_gpu_mem_util: float = 0.90
    # 0 = let Atlas pick its default concurrency.
    atlas_max_num_seqs: int = 0
    atlas_oom_guard_mb: int = 0
    # NVMe KV offload (High-Speed Swap) for very long context on a single Spark.
    atlas_high_speed_swap: bool = False
    atlas_high_speed_swap_dir: str = ""
    atlas_hss_cache_blocks_per_seq: int = 64

    # Runtime
    helper_dir: Path = field(default_factory=lambda: Path.home() / ".spark-serve")

    # ── Engine-aware service handles (shared lifecycle/tunnel/health code) ──────────
    @property
    def service_port(self) -> int:
        return self.atlas_port if self.engine == "atlas" else self.vllm_port

    @property
    def served_model_name(self) -> str:
        return self.atlas_model if self.engine == "atlas" else _SERVED_MODEL


def engine_label(cfg) -> str:
    return "Atlas" if getattr(cfg, "engine", "vllm") == "atlas" else "vLLM"


def _should_remove_container(cfg: "Config") -> bool:
    return os.environ.get("VLLM_REMOVE_CONTAINER", "").lower() in (
        "1",
        "true",
        "yes",
    ) or os.environ.get("VLLM_FORCE_RESTART", "").lower() in ("1", "true", "yes")


def _boot_time_hint(cfg: "Config") -> str:
    if cfg.optimization_level <= 0:
        return "~1-2 min first boot (O0, no CUDA graphs)"
    if cfg.optimization_level == 1:
        return "~3-5 min first boot (O1); restarts faster with compile cache"
    if cfg.max_cudagraph_capture_size <= cfg.max_num_seqs:
        return "~4-7 min first boot; restarts ~1-3 min with compile cache"
    return "~7-10 min first boot (full CUDA graph capture)"


def _apply_env_overrides(cfg: "Config") -> None:
    """Tune boot time vs throughput via env vars (see `make run` help)."""
    if os.environ.get("VLLM_PRODUCTION", "").lower() in ("1", "true", "yes"):
        cfg.optimization_level = 2
        cfg.max_batched_tokens = 32768
    elif level := os.environ.get("VLLM_OPTIMIZATION_LEVEL"):
        cfg.optimization_level = int(level)
    if os.environ.get("VLLM_FAST_BOOT", "").lower() in ("1", "true", "yes"):
        cfg.optimization_level = 0
        cfg.max_cudagraph_capture_size = min(cfg.max_cudagraph_capture_size, cfg.max_num_seqs)
        cfg.max_batched_tokens = min(cfg.max_batched_tokens, 16384)
    if size := os.environ.get("VLLM_MAX_CUDAGRAPH_CAPTURE_SIZE"):
        cfg.max_cudagraph_capture_size = int(size)
    if tokens := os.environ.get("VLLM_MAX_BATCHED_TOKENS"):
        cfg.max_batched_tokens = int(tokens)
    if cache := os.environ.get("VLLM_COMPILE_CACHE_DIR"):
        cfg.compile_cache_dir = Path(cache).expanduser()
    if hostname := os.environ.get("CF_TUNNEL_HOSTNAME"):
        cfg.cf_tunnel_hostname = hostname
    if name := os.environ.get("CF_TUNNEL_NAME"):
        cfg.cf_tunnel_name = name
    if model_len := os.environ.get("VLLM_MAX_MODEL_LEN"):
        cfg.max_model_len = int(model_len)
    if kv_dtype := os.environ.get("VLLM_KV_CACHE_DTYPE"):
        cfg.kv_cache_dtype = kv_dtype
    if rope := os.environ.get("VLLM_ROPE_SCALING"):
        cfg.rope_scaling_enabled = rope.lower() not in ("0", "false", "no", "off")
    if native := os.environ.get("VLLM_NATIVE_CONTEXT_LEN"):
        cfg.native_context_len = int(native)
    if backend := os.environ.get("VLLM_ATTENTION_BACKEND"):
        cfg.attention_backend = backend
    if k := os.environ.get("VLLM_DFLASH_K"):
        cfg.dflash_num_spec_tokens = int(k)
    if seqs := os.environ.get("VLLM_MAX_NUM_SEQS"):
        # ⚠️  > 16 can freeze the box during torch.compile on GB10 — experiment with care.
        cfg.max_num_seqs = int(seqs)
    if os.environ.get("VLLM_FLASHINFER_MOE_FP4", "").lower() in ("1", "true", "yes"):
        cfg.flashinfer_moe_fp4 = True
    if moe_backend := os.environ.get("VLLM_FLASHINFER_MOE_BACKEND"):
        cfg.flashinfer_moe_backend = moe_backend

    # ── Engine selection + Atlas overrides ──────────────────────────────────────
    if engine := (os.environ.get("ENGINE") or os.environ.get("LLM_ENGINE")):
        cfg.engine = engine.strip().lower()
    if img := os.environ.get("ATLAS_IMAGE"):
        cfg.atlas_image = img
    if model := os.environ.get("ATLAS_MODEL"):
        cfg.atlas_model = model
    if port := os.environ.get("ATLAS_PORT"):
        cfg.atlas_port = int(port)
    if seq := (os.environ.get("ATLAS_MAX_SEQ_LEN") or os.environ.get("MAX_SEQ_LEN")):
        cfg.atlas_max_seq_len = int(seq)
    if kv := (os.environ.get("ATLAS_KV_CACHE_DTYPE") or os.environ.get("KV_CACHE_DTYPE")):
        cfg.atlas_kv_cache_dtype = kv
    if hp := os.environ.get("ATLAS_KV_HIGH_PRECISION_LAYERS"):
        cfg.atlas_kv_high_precision_layers = hp
    if os.environ.get("ATLAS_NO_SPECULATIVE", "").lower() in ("1", "true", "yes"):
        cfg.atlas_speculative = False
    if drafts := os.environ.get("ATLAS_NUM_DRAFTS"):
        cfg.atlas_num_drafts = int(drafts)
    if policy := os.environ.get("ATLAS_SCHEDULING_POLICY"):
        cfg.atlas_scheduling_policy = policy
    if os.environ.get("ATLAS_DISABLE_PREFIX_CACHING", "").lower() in ("1", "true", "yes"):
        cfg.atlas_enable_prefix_caching = False
    if parser := os.environ.get("ATLAS_TOOL_CALL_PARSER"):
        cfg.atlas_tool_call_parser = parser
    if gmu := (os.environ.get("ATLAS_GPU_MEM_UTIL") or os.environ.get("GPU_MEMORY_UTILIZATION")):
        cfg.atlas_gpu_mem_util = float(gmu)
    if seqs := os.environ.get("ATLAS_MAX_NUM_SEQS"):
        cfg.atlas_max_num_seqs = int(seqs)
    if oom := os.environ.get("ATLAS_OOM_GUARD_MB"):
        cfg.atlas_oom_guard_mb = int(oom)
    if hss_dir := os.environ.get("ATLAS_HIGH_SPEED_SWAP_DIR"):
        cfg.atlas_high_speed_swap_dir = hss_dir
        cfg.atlas_high_speed_swap = True
    if os.environ.get("ATLAS_HIGH_SPEED_SWAP", "").lower() in ("1", "true", "yes"):
        cfg.atlas_high_speed_swap = True
    if hss_blocks := os.environ.get("ATLAS_HSS_CACHE_BLOCKS_PER_SEQ"):
        cfg.atlas_hss_cache_blocks_per_seq = int(hss_blocks)

    # When running Atlas, unify the shared service handles so all the lifecycle,
    # tunnel, health, helper, and metrics code targets the Atlas container/port.
    if cfg.engine == "atlas":
        cfg.container_name = cfg.atlas_container
        cfg.vllm_port = cfg.atlas_port
        cfg.vllm_image = cfg.atlas_image
        cfg.gpu_mem_util = cfg.atlas_gpu_mem_util
