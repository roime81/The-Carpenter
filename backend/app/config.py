from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("CARPENTER_APP_NAME", "The Carpenter")
    environment: str = os.getenv("CARPENTER_ENV", "development")
    database_path: str = os.getenv("CARPENTER_DB_PATH", "./data/carpenter.db")
    agent_enrollment_token: str = os.getenv("CARPENTER_AGENT_ENROLLMENT_TOKEN", "")
    agent_stale_seconds: int = max(30, int(os.getenv("CARPENTER_AGENT_STALE_SECONDS", "90")))
    cookie_secure: bool = os.getenv("CARPENTER_COOKIE_SECURE", "false").lower() == "true"
    llm_provider: str = os.getenv("CARPENTER_LLM_PROVIDER", "none")
    llm_model: str = os.getenv("CARPENTER_LLM_MODEL", "llama3.1:8b")
    llm_base_url: str = os.getenv("CARPENTER_LLM_BASE_URL", "http://127.0.0.1:11434")
    llm_api_key: str = os.getenv("CARPENTER_LLM_API_KEY", "")
    llm_timeout_seconds: int = int(os.getenv("CARPENTER_LLM_TIMEOUT_SECONDS", "20"))


settings = Settings()
