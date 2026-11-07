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

    # --- CQA: LLM-оценка диалогов ---
    # Провайдер: "gemini" (реальный вызов) или "mock" (офлайн-заглушка для разработки UI/тестов).
    # Если GEMINI_API_KEY пуст, автоматически используется mock.
    llm_provider: Literal["gemini", "mock"] = "gemini"
    gemini_api_key: str = ""  # задаётся ТОЛЬКО в .env (файл в .gitignore)
    gemini_model: str = "gemini-3.5-flash-lite"
    # minimal | low | medium | high — больше «думания» = точнее, но дороже и медленнее
    gemini_thinking_level: str = "medium"
    llm_timeout_seconds: float = 120
    llm_max_retries: int = 3
    llm_batch_concurrency: int = 4  # общий предел оценок на процесс: batch + одиночные
    # Цены за 1M токенов (USD) — для расчёта стоимости оценки. Thinking-токены = output.
    llm_price_input_per_1m: float = 1.50
    llm_price_output_per_1m: float = 7.50

    # API организаторов: GET {dataset_api_url}?group_id=DEV
    dataset_api_url: str = ""
    dataset_timeout_seconds: float = 30

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
