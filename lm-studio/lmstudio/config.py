"""LM Studio tunnel configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    vault_token: str = ""
    vault_addr: str = "https://secret-store.chrisvouga.dev"
    vault_mount: str = "secret"
    vault_project: str = "personal"
    vault_config: str = "dev"

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
    if addr := os.environ.get("VAULT_ADDR"):
        cfg.vault_addr = addr
    if mount := os.environ.get("VAULT_MOUNT"):
        cfg.vault_mount = mount
    if project := os.environ.get("VAULT_PROJECT"):
        cfg.vault_project = project
    if config := os.environ.get("VAULT_CONFIG"):
        cfg.vault_config = config
    if port := os.environ.get("LM_STUDIO_PORT"):
        cfg.lm_studio_port = int(port)
    if hostname := os.environ.get("CF_TUNNEL_HOSTNAME"):
        cfg.cf_tunnel_hostname = hostname
    if name := os.environ.get("CF_TUNNEL_NAME"):
        cfg.cf_tunnel_name = name
