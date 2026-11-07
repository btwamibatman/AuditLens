"""Хранение файлов на диске (UPLOAD_DIR). Файлы раздаются по /uploads/<name>.

Для облака (S3 и т.п.) достаточно переписать save_upload / list_uploads — роутер не меняется.
"""

import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import AppError

CHUNK_SIZE = 1024 * 1024
PUBLIC_PREFIX = "/uploads"


class UploadRead(BaseModel):
    name: str
    url: str
    size: int
    content_type: str
    created_at: datetime


def upload_dir() -> Path:
    path = Path(get_settings().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _to_read(path: Path) -> UploadRead:
    stat = path.stat()
    return UploadRead(
        name=path.name,
        url=f"{PUBLIC_PREFIX}/{path.name}",
        size=stat.st_size,
        content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        created_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


async def save_upload(file: UploadFile) -> UploadRead:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    suffix = Path(file.filename or "").suffix.lower()[:10]
    target = upload_dir() / f"{uuid.uuid4().hex}{suffix}"

    written = 0
    with target.open("wb") as out:
        while chunk := await file.read(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise AppError(f"File is larger than {get_settings().max_upload_mb} MB")
            out.write(chunk)
    return _to_read(target)


def list_uploads() -> list[UploadRead]:
    files = [p for p in upload_dir().iterdir() if p.is_file() and not p.name.startswith(".")]
    return [_to_read(p) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]
