"""Общие Pydantic-схемы."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Ответ для списков: {"items": [...], "total": 42}."""

    items: list[T]
    total: int
