"""The Config dataclass + env overrides."""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Docker label used to detect when a running container's launch config is stale.
_CONFIG_HASH_LABEL = "spark-serve.config-hash"


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

    # Cloudflare tunnel
    cf_tunnel_name: str = "llm"
    cf_tunnel_hostname: str = "llm.chrisvouga.dev"

    # Atlas (Qwen3-Coder-Next NVFP4 on GB10)
    atlas_image: str = "avarok/atlas-gb10:latest"
    atlas_model: str = "RedHatAI/Qwen3-Coder-Next-NVFP4"
    atlas_container: str = "atlas"
    atlas_port: int = 8888
    atlas_max_seq_len: int = 131072
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
        return self.atlas_port


def _should_remove_container(cfg: "Config") -> bool:
    return os.environ.get("ATLAS_FORCE_RESTART", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _apply_env_overrides(cfg: "Config") -> None:
    if hostname := os.environ.get("CF_TUNNEL_HOSTNAME"):
        cfg.cf_tunnel_hostname = hostname
    if name := os.environ.get("CF_TUNNEL_NAME"):
        cfg.cf_tunnel_name = name
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

    cfg.container_name = cfg.atlas_container
