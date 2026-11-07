"""Точка входа: uvicorn app.main:app --reload"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import build_api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    prefix = settings.api_prefix

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=f"{prefix}/docs",
        redoc_url=None,
        openapi_url=f"{prefix}/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(build_api_router(settings), prefix=prefix)

    if settings.enable_uploads:
        from app.features.uploads.service import PUBLIC_PREFIX, upload_dir

        app.mount(PUBLIC_PREFIX, StaticFiles(directory=upload_dir()), name="uploads")

    _mount_frontend(app, Path(settings.frontend_dist), prefix)
    return app


def _mount_frontend(app: FastAPI, dist: Path, api_prefix: str) -> None:
    """Если фронтенд собран (npm run build), отдаём его с того же порта — удобно для деплоя."""
    index = dist / "index.html"
    if not index.is_file():
        return
    dist = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(api_prefix.strip("/") + "/"):
            raise HTTPException(status_code=404)
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(index)


app = create_app()
