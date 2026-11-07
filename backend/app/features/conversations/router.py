from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.db import DbSession
from app.features.conversations import service
from app.features.conversations.schemas import (
    ConversationImport,
    ConversationRead,
    ConversationSummary,
    ImportResult,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    db: DbSession, dataset_group: str | None = None, language: str | None = None
):
    return service.list_conversations(db, dataset_group=dataset_group, language=language)


@router.get("/{conversation_id}", response_model=ConversationRead)
def get_conversation(conversation_id: str, db: DbSession):
    return service.get_conversation(db, conversation_id)


@router.get("/{conversation_id}/audio")
def get_conversation_audio(conversation_id: str, db: DbSession):
    """Стриминг аудиозаписи звонка напрямую в аудиоплеер интерфейса."""
    stream, headers, status_code = service.resolve_audio_stream(db, conversation_id)
    return StreamingResponse(stream, status_code=status_code, headers=headers)


@router.post("/sync", response_model=ImportResult)
def sync_dataset(db: DbSession, group_id: str = "DEV"):
    """Загрузить набор из API организаторов по group_id (DEV или контрольный)."""
    return service.sync_dataset(db, group_id)


@router.post("/import", response_model=ImportResult)
def import_conversations(data: ConversationImport, db: DbSession):
    """Загрузить транскрипты вручную (тот же формат записей, что у API организаторов)."""
    return service.upsert_records(db, data.dataset_group, data.records)
