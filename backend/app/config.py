from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("CARPENTER_APP_NAME", "The Carpenter")
    environment: str = os.getenv("CARPENTER_ENV", "development")
    database_path: str = os.getenv("CARPENTER_DB_PATH", "./data/carpenter.db")
    agent_enrollment_token: str = os.getenv("CARPENTER_AGENT_ENROLLMENT_TOKEN", "")
    admin_token: str = os.getenv("CARPENTER_ADMIN_TOKEN", "")
    operator_token: str = os.getenv("CARPENTER_OPERATOR_TOKEN", "")
    viewer_token: str = os.getenv("CARPENTER_VIEWER_TOKEN", "")
    session_secret: str = os.getenv("CARPENTER_SESSION_SECRET", os.getenv("CARPENTER_ADMIN_TOKEN", ""))
    agent_stale_seconds: int = max(30, int(os.getenv("CARPENTER_AGENT_STALE_SECONDS", "90")))
    worker_lease_seconds: int = max(15, min(600, int(os.getenv("CARPENTER_WORKER_LEASE_SECONDS", "600"))))
    cookie_secure: bool = os.getenv("CARPENTER_COOKIE_SECURE", "false").lower() == "true"
    llm_provider: str = os.getenv("CARPENTER_LLM_PROVIDER", "none")
    llm_model: str = os.getenv("CARPENTER_LLM_MODEL", "llama3.1:8b")
    llm_base_url: str = os.getenv("CARPENTER_LLM_BASE_URL", "http://127.0.0.1:11434")
    llm_api_key: str = os.getenv("CARPENTER_LLM_API_KEY", "")
    llm_timeout_seconds: int = int(os.getenv("CARPENTER_LLM_TIMEOUT_SECONDS", "20"))


settings = Settings()
