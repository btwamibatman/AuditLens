"""Сборка всех роутеров под /api. Новая фича = одна строка include_router здесь."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import DbSession
from app.features.items.router import router as items_router


class Features(BaseModel):
    auth: bool
    uploads: bool
    ai: bool


class Meta(BaseModel):
    app_name: str
    environment: str
    features: Features


def build_api_router(settings: Settings) -> APIRouter:
    api = APIRouter()

    @api.get("/health", tags=["system"])
    def health(db: DbSession):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @api.get("/meta", response_model=Meta, tags=["system"])
    def meta():
        """Фронтенд читает отсюда название и включённые модули."""
        return Meta(
            app_name=settings.app_name,
            environment=settings.environment,
            features=Features(
                auth=settings.enable_auth, uploads=settings.enable_uploads, ai=settings.enable_ai
            ),
        )

    # --- Фичи проекта: добавляйте сюда ---
    api.include_router(items_router)

    # --- Опциональные модули (флаги в .env) ---
    if settings.enable_auth:
        from app.features.auth.router import router as auth_router

        api.include_router(auth_router)
    if settings.enable_uploads:
        from app.features.uploads.router import router as uploads_router

        api.include_router(uploads_router)
    if settings.enable_ai:
        from app.features.ai.router import router as ai_router

        api.include_router(ai_router)

    return api
