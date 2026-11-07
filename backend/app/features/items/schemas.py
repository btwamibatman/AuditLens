"""Контракт API: что принимаем и что отдаём."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemStatus = Literal["todo", "in_progress", "done"]


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ItemStatus = "todo"


class ItemUpdate(BaseModel):
    """PATCH: все поля необязательные, обновляются только переданные."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ItemStatus | None = None


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: ItemStatus
    created_at: datetime
    updated_at: datetime
