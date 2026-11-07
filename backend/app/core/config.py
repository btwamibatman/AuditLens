"""Все настройки приложения. Значения берутся из переменных окружения / корневого .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Один общий .env в корне репозитория; backend/.env (если есть) переопределяет его.
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Приложение ---
    app_name: str = "Launchpad"
    environment: Literal["dev", "prod", "test"] = "dev"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- База данных ---
    # SQLite по умолчанию. Для Postgres: postgresql+psycopg://app:app@localhost:5432/app
    database_url: str = "sqlite:///./data/app.db"

    # --- Модули (включаются по необходимости) ---
    enable_auth: bool = False
    enable_uploads: bool = False
    enable_ai: bool = False

    # --- Auth ---
    secret_key: str = "dev-secret-change-me-please-32-bytes-min"
    access_token_expire_minutes: int = 60 * 24 * 7

    # --- Uploads ---
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 10

    # --- AI (любой OpenAI-совместимый API: OpenAI, Groq, OpenRouter, Ollama, LM Studio...) ---
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 60

    # --- Раздача собранного фронтенда (prod / Docker) ---
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
