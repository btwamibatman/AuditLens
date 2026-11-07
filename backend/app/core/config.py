"""Все настройки приложения. Значения берутся из переменных окружения / корневого .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AuditLens"
    environment: Literal["dev", "prod", "test"] = "dev"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "sqlite:///./data/app.db"

    enable_auth: bool = False
    enable_uploads: bool = False
    enable_ai: bool = False

    secret_key: str = "dev-secret-change-me-please-32-bytes-min"
    access_token_expire_minutes: int = 60 * 24 * 7

    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 10

    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 60

    frontend_dist: str = str(ROOT_DIR / "frontend" / "dist")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
