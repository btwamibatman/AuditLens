from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    # conversation_id из датасета организаторов, напр. "p1-ru-001"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    dataset_group: Mapped[str] = mapped_column(String(50), default="manual", index=True)
    channel: Mapped[str] = mapped_column(String(30))  # "agent chat" | "voice call"
    language: Mapped[str] = mapped_column(String(5), index=True)  # RU | KZ | EN
    # [{"timestamp": "00:02", "speaker": "operator", "text": "..."}] — метки времени как в источнике
    transcript: Mapped[list] = mapped_column(JSON)
    audio_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
