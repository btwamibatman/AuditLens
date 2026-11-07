from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Speaker = Literal["client", "operator", "bot", "system"]


class Utterance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: str = ""
    speaker: Speaker
    text: str = ""


class ConversationRecord(BaseModel):
    """Запись в формате API организаторов."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(min_length=1, max_length=100)
    channel: str = "agent chat"
    language: str = "RU"
    transcript: list[Utterance] = Field(min_length=1)
    audio_url: str | None = None


class ConversationImport(BaseModel):
    dataset_group: str = "manual"
    records: list[ConversationRecord] = Field(min_length=1)


class ImportResult(BaseModel):
    dataset_group: str
    created: int
    updated: int
    total: int


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_group: str
    channel: str
    language: str
    audio_url: str | None
    created_at: datetime


class ConversationRead(ConversationSummary):
    transcript: list[Utterance]
