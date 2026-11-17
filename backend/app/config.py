from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("CARPENTER_APP_NAME", "The Carpenter")
    environment: str = os.getenv("CARPENTER_ENV", "development")
    database_path: str = os.getenv("CARPENTER_DB_PATH", "./data/carpenter.db")
    agent_enrollment_token: str = os.getenv("CARPENTER_AGENT_ENROLLMENT_TOKEN", "")
    cookie_secure: bool = os.getenv("CARPENTER_COOKIE_SECURE", "false").lower() == "true"


settings = Settings()
