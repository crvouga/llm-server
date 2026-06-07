"""LM Studio tunnel configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    doppler_token: str = ""
    doppler_project: str = "personal"
    doppler_config: str = "dev"

    cf_api_token: str = ""
    cf_account_id: str = ""
    cf_tunnel_token: str = ""

    cf_tunnel_name: str = "llm"
    cf_tunnel_hostname: str = "llm.chrisvouga.dev"

    lm_studio_port: int = 1234
    helper_dir: Path = field(default_factory=lambda: Path.home() / ".lm-studio-tunnel")

    @property
    def service_port(self) -> int:
        return self.lm_studio_port


def apply_env_overrides(cfg: Config) -> None:
    if port := os.environ.get("LM_STUDIO_PORT"):
        cfg.lm_studio_port = int(port)
    if hostname := os.environ.get("CF_TUNNEL_HOSTNAME"):
        cfg.cf_tunnel_hostname = hostname
    if name := os.environ.get("CF_TUNNEL_NAME"):
        cfg.cf_tunnel_name = name
