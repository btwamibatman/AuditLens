"""Доменные ошибки. Сервисы бросают их, не зная про HTTP; здесь они превращаются в ответы."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    default_message = "Bad request"

    def __init__(self, message: str | None = None, *, code: str | None = None):
        self.message = message or self.default_message
        self.code = code
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    default_message = "Not found"


class ConflictError(AppError):
    status_code = 409
    default_message = "Already exists"


class UnauthorizedError(AppError):
    status_code = 401
    default_message = "Not authenticated"


class ForbiddenError(AppError):
    status_code = 403
    default_message = "Forbidden"


class ExternalServiceError(AppError):
    status_code = 502
    default_message = "External service error"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        # Формат совпадает с HTTPException FastAPI: {"detail": "..."}
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.message, "code": exc.code}
        )
