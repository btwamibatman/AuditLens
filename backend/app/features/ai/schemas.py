from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    system: str | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)


class ChatResponse(BaseModel):
    reply: str
    model: str
    mock: bool = False
