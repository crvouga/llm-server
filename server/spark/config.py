"""The Config dataclass + env overrides."""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Docker label used to detect when a running container's launch config is stale.
_CONFIG_HASH_LABEL = "spark-serve.config-hash"

_VALID_ENGINES = frozenset({"vllm", "atlas"})


@dataclass
class Config:
    # Vault / OpenBao
    vault_token: str = ""
    vault_addr: str = "https://secret-store.chrisvouga.dev"
    vault_mount: str = "secret"
    vault_project: str = "personal"
    vault_config: str = "dev"

    # Secrets — populated from the secret store
    cf_api_token: str = ""
    cf_account_id: str = ""
    cf_tunnel_token: str = ""
    hf_token: str = ""

    # Cloudflare tunnel
    cf_tunnel_name: str = "llm"
    cf_tunnel_hostname: str = "llm.chrisvouga.dev"

    # Inference engine: vllm (default) or atlas (legacy)
    engine: str = "vllm"

    # vLLM (Qwen3-Coder-Next NVFP4-GB10 + DFlash on GB10)
    vllm_image: str = "nvcr.io/nvidia/vllm:26.01-py3"
    vllm_model: str = "saricles/Qwen3-Coder-Next-NVFP4-GB10"
    vllm_dflash_model: str = "z-lab/Qwen3-Coder-Next-DFlash"
    vllm_container: str = "vllm"
    vllm_port: int = 8888
    vllm_served_model_name: str = "atlas"
    vllm_max_model_len: int = 131072
    vllm_kv_cache_dtype: str = "fp8"
    vllm_gpu_mem_util: float = 0.60
    vllm_speculative: bool = True
    vllm_dflash_tokens: int = 15
    vllm_enforce_eager: bool = True
    vllm_attention_backend: str = "flashinfer"
    vllm_load_format: str = "fastsafetensors"
    vllm_moe_backend: str = "cutlass"
    vllm_extra_env: dict[str, str] = field(default_factory=dict)

    # Atlas (Qwen3-Coder-Next NVFP4 on GB10)
    atlas_image: str = "avarok/atlas-gb10:latest"
    atlas_model: str = "RedHatAI/Qwen3-Coder-Next-NVFP4"
    atlas_container: str = "atlas"
    atlas_port: int = 8888
    atlas_max_seq_len: int = 131072
    # GB10 + 128K fp8 KV fits ~6 concurrent max-length sequences (Atlas default batch 8 OOMs).
    atlas_max_batch_size: int = 6
    atlas_kv_cache_dtype: str = "fp8"
    atlas_speculative: bool = True
    atlas_num_drafts: int = 2
    # Required for MoE MTP on qwen3_next (Qwen3-Coder-Next / Qwen3-Next-80B family).
    atlas_mtp_quantization: str = "nvfp4"
    atlas_gpu_mem_util: float = 0.88
    # 0 = omit --max-thinking-budget (thinking off by default; proxy injects opt-out).
    atlas_max_thinking_budget: int = 0
    atlas_oom_guard_mb: int = 1024
    # qwen3_next GDN layers: disable SSM snapshot slots to save ~GB during boot.
    atlas_ssm_cache_slots: int = 0

    # Runtime
    helper_dir: Path = field(default_factory=lambda: Path.home() / ".spark-serve")
    container_name: str = "atlas"
    docker_cmd: list = field(default_factory=lambda: ["docker"])

    @property
    def service_port(self) -> int:
        if self.engine == "atlas":
            return self.atlas_port
        return self.vllm_port


def _should_remove_container(cfg: "Config") -> bool:
    for key in ("ENGINE_FORCE_RESTART", "VLLM_FORCE_RESTART", "ATLAS_FORCE_RESTART"):
        if os.environ.get(key, "").lower() in ("1", "true", "yes"):
            return True
    return False


def _apply_env_overrides(cfg: "Config") -> None:
    if addr := os.environ.get("VAULT_ADDR"):
        cfg.vault_addr = addr
    if mount := os.environ.get("VAULT_MOUNT"):
        cfg.vault_mount = mount
    if project := os.environ.get("VAULT_PROJECT"):
        cfg.vault_project = project
    if config := os.environ.get("VAULT_CONFIG"):
        cfg.vault_config = config
    if hostname := os.environ.get("CF_TUNNEL_HOSTNAME"):
        cfg.cf_tunnel_hostname = hostname
    if name := os.environ.get("CF_TUNNEL_NAME"):
        cfg.cf_tunnel_name = name
    if engine := os.environ.get("ENGINE"):
        engine = engine.strip().lower()
        if engine in _VALID_ENGINES:
            cfg.engine = engine
    if img := os.environ.get("VLLM_IMAGE"):
        cfg.vllm_image = img
    if model := os.environ.get("VLLM_MODEL"):
        cfg.vllm_model = model
    if dflash := os.environ.get("VLLM_DFLASH_MODEL"):
        cfg.vllm_dflash_model = dflash
    if port := os.environ.get("VLLM_PORT"):
        cfg.vllm_port = int(port)
    if served := os.environ.get("VLLM_SERVED_MODEL_NAME"):
        cfg.vllm_served_model_name = served
    if seq := (os.environ.get("VLLM_MAX_MODEL_LEN") or os.environ.get("MAX_MODEL_LEN")):
        cfg.vllm_max_model_len = int(seq)
    if kv := (os.environ.get("VLLM_KV_CACHE_DTYPE") or os.environ.get("KV_CACHE_DTYPE")):
        cfg.vllm_kv_cache_dtype = kv
    if gmu := (os.environ.get("VLLM_GPU_MEM_UTIL") or os.environ.get("GPU_MEMORY_UTILIZATION")):
        cfg.vllm_gpu_mem_util = float(gmu)
    if os.environ.get("VLLM_NO_SPECULATIVE", "").lower() in ("1", "true", "yes"):
        cfg.vllm_speculative = False
    if tokens := os.environ.get("VLLM_DFLASH_TOKENS"):
        cfg.vllm_dflash_tokens = int(tokens)
    if os.environ.get("VLLM_ENFORCE_EAGER", "").lower() in ("0", "false", "no"):
        cfg.vllm_enforce_eager = False
    if backend := os.environ.get("VLLM_ATTENTION_BACKEND"):
        cfg.vllm_attention_backend = backend
    if load_fmt := os.environ.get("VLLM_LOAD_FORMAT"):
        cfg.vllm_load_format = load_fmt
    if moe := os.environ.get("VLLM_MOE_BACKEND"):
        cfg.vllm_moe_backend = moe
    if img := os.environ.get("ATLAS_IMAGE"):
        cfg.atlas_image = img
    if model := os.environ.get("ATLAS_MODEL"):
        cfg.atlas_model = model
    if port := os.environ.get("ATLAS_PORT"):
        cfg.atlas_port = int(port)
    if seq := (os.environ.get("ATLAS_MAX_SEQ_LEN") or os.environ.get("MAX_SEQ_LEN")):
        cfg.atlas_max_seq_len = int(seq)
    if batch := os.environ.get("ATLAS_MAX_BATCH_SIZE"):
        cfg.atlas_max_batch_size = int(batch)
    if kv := (os.environ.get("ATLAS_KV_CACHE_DTYPE") or os.environ.get("KV_CACHE_DTYPE")):
        cfg.atlas_kv_cache_dtype = kv
    if os.environ.get("ATLAS_NO_SPECULATIVE", "").lower() in ("1", "true", "yes"):
        cfg.atlas_speculative = False
    if drafts := os.environ.get("ATLAS_NUM_DRAFTS"):
        cfg.atlas_num_drafts = int(drafts)
    if mtp := os.environ.get("ATLAS_MTP_QUANTIZATION"):
        cfg.atlas_mtp_quantization = mtp
    if gmu := (os.environ.get("ATLAS_GPU_MEM_UTIL") or os.environ.get("GPU_MEMORY_UTILIZATION")):
        cfg.atlas_gpu_mem_util = float(gmu)
    if budget := os.environ.get("ATLAS_MAX_THINKING_BUDGET"):
        cfg.atlas_max_thinking_budget = int(budget)
    if guard := os.environ.get("ATLAS_OOM_GUARD_MB"):
        cfg.atlas_oom_guard_mb = int(guard)
    if slots := os.environ.get("ATLAS_SSM_CACHE_SLOTS"):
        cfg.atlas_ssm_cache_slots = int(slots)

    cfg.container_name = (
        cfg.atlas_container if cfg.engine == "atlas" else cfg.vllm_container
    )
