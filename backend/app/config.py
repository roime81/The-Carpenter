from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("CARPENTER_APP_NAME", "The Carpenter")
    environment: str = os.getenv("CARPENTER_ENV", "development")
    database_path: str = os.getenv("CARPENTER_DB_PATH", "./data/carpenter.db")
    agent_enrollment_token: str = os.getenv("CARPENTER_AGENT_ENROLLMENT_TOKEN", "")
    admin_token: str = os.getenv("CARPENTER_ADMIN_TOKEN", os.getenv("CARPENTER_AGENT_ENROLLMENT_TOKEN", ""))
    agent_stale_seconds: int = max(30, int(os.getenv("CARPENTER_AGENT_STALE_SECONDS", "90")))
    worker_lease_seconds: int = max(15, min(600, int(os.getenv("CARPENTER_WORKER_LEASE_SECONDS", "90"))))
    cookie_secure: bool = os.getenv("CARPENTER_COOKIE_SECURE", "false").lower() == "true"
    llm_provider: str = os.getenv("CARPENTER_LLM_PROVIDER", "none")
    llm_model: str = os.getenv("CARPENTER_LLM_MODEL", "llama3.1:8b")
    llm_base_url: str = os.getenv("CARPENTER_LLM_BASE_URL", "http://127.0.0.1:11434")
    llm_api_key: str = os.getenv("CARPENTER_LLM_API_KEY", "")
    llm_timeout_seconds: int = int(os.getenv("CARPENTER_LLM_TIMEOUT_SECONDS", "20"))
    proxmox_url: str = os.getenv("CARPENTER_PROXMOX_URL", "")
    proxmox_token_id: str = os.getenv("CARPENTER_PROXMOX_TOKEN_ID", "")
    proxmox_token_secret: str = os.getenv("CARPENTER_PROXMOX_TOKEN_SECRET", "")
    proxmox_node: str = os.getenv("CARPENTER_PROXMOX_NODE", "")
    proxmox_template_vmid: int = int(os.getenv("CARPENTER_PROXMOX_TEMPLATE_VMID", "0"))
    gamgee_installer_url: str = os.getenv("CARPENTER_GAMGEE_INSTALLER_URL", "")
    gamgee_installer_token: str = os.getenv("CARPENTER_GAMGEE_INSTALLER_TOKEN", "")
    kubernetes_api_url: str = os.getenv("CARPENTER_KUBERNETES_API_URL", "")
    kubernetes_token: str = os.getenv("CARPENTER_KUBERNETES_TOKEN", "")


settings = Settings()
