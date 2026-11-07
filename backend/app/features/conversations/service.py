import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ExternalServiceError, NotFoundError
from app.features.conversations.models import Conversation
from app.features.conversations.schemas import ConversationRecord, ImportResult


def is_call(channel: str) -> bool:
    return "call" in channel.lower() or "voice" in channel.lower()


def list_conversations(
    db: Session, *, dataset_group: str | None = None, language: str | None = None
) -> list[Conversation]:
    stmt = select(Conversation).order_by(Conversation.id)
    if dataset_group:
        stmt = stmt.where(Conversation.dataset_group == dataset_group)
    if language:
        stmt = stmt.where(Conversation.language == language.upper())
    return list(db.scalars(stmt))


def get_conversation(db: Session, conversation_id: str) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise NotFoundError(f"Conversation {conversation_id} not found")
    return conv


def _validate_unique_records(records: list[ConversationRecord]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for rec in records:
        cid = rec.conversation_id.strip()
        if not cid or cid != rec.conversation_id:
            raise AppError("Conversation ID must not be blank or padded with whitespace")
        if cid in seen and cid not in duplicates:
            duplicates.append(cid)
        seen.add(cid)
    if duplicates:
        raise AppError(f"Duplicate conversation_id in dataset: {', '.join(duplicates)}")


def upsert_records(
    db: Session, dataset_group: str, records: list[ConversationRecord]
) -> ImportResult:
    _validate_unique_records(records)
    created = updated = 0
    for rec in records:
        conv = db.get(Conversation, rec.conversation_id)
        payload = {
            "dataset_group": dataset_group,
            "channel": rec.channel,
            "language": rec.language.upper(),
            "transcript": [u.model_dump() for u in rec.transcript],
            "audio_url": rec.audio_url,
        }
        if conv is None:
            db.add(Conversation(id=rec.conversation_id, **payload))
            created += 1
        else:
            for key, value in payload.items():
                setattr(conv, key, value)
            updated += 1
    db.commit()
    return ImportResult(
        dataset_group=dataset_group, created=created, updated=updated, total=len(records)
    )


def fetch_dataset(group_id: str) -> list[ConversationRecord]:
    """GET {DATASET_API_URL}?group_id=... — через бэкенд, чтобы не упираться в CORS."""
    settings = get_settings()
    if not settings.dataset_api_url:
        raise AppError("DATASET_API_URL is not configured in .env")
    try:
        resp = httpx.get(
            settings.dataset_api_url,
            params={"group_id": group_id},
            timeout=settings.dataset_timeout_seconds,
            follow_redirects=True,
        )
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"Dataset API is unavailable: {exc}") from exc
    except ValueError as exc:
        raise ExternalServiceError("Dataset API returned non-JSON response") from exc

    if not isinstance(body, dict) or not body.get("isSuccess", False):
        err_msg = body.get("error") if isinstance(body, dict) else "invalid response structure"
        raise ExternalServiceError(f"Dataset API error: {err_msg or 'unknown'}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise ExternalServiceError("Dataset API returned missing data object")
    returned_group = data.get("dataset_group_id")
    if returned_group is not None and returned_group != group_id:
        raise ExternalServiceError(
            f"Dataset API group mismatch: requested {group_id}, got {returned_group}"
        )
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise ExternalServiceError("Dataset API returned no records")
    total_records = data.get("total_records")
    if isinstance(total_records, int) and total_records != len(records):
        raise ExternalServiceError(
            f"Dataset API count mismatch: total_records={total_records}, actual={len(records)}"
        )

    try:
        parsed = [ConversationRecord.model_validate(r) for r in records]
    except ValidationError as exc:
        raise ExternalServiceError(f"Dataset API returned invalid record: {exc}") from exc

    _validate_unique_records(parsed)
    return parsed


def sync_dataset(db: Session, group_id: str) -> ImportResult:
    return upsert_records(db, group_id, fetch_dataset(group_id))
