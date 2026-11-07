"""Тонкий клиент для OpenAI-совместимого /chat/completions.

Работает с OpenAI, Groq, OpenRouter, Together, Ollama (http://localhost:11434/v1), LM Studio и др.
Если AI_API_KEY пуст — возвращает mock-ответ, чтобы фронтенд можно было делать без ключа.
"""

import httpx

from app.core.config import get_settings
from app.core.errors import ExternalServiceError
from app.features.ai.schemas import ChatMessage, ChatRequest, ChatResponse


def chat(request: ChatRequest) -> ChatResponse:
    settings = get_settings()
    messages = list(request.messages)
    if request.system:
        messages.insert(0, ChatMessage(role="system", content=request.system))

    if not settings.ai_api_key:
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return ChatResponse(
            reply=f"🤖 Mock-ответ (AI_API_KEY не задан). Вы написали: «{last}»",
            model="mock",
            mock=True,
        )

    try:
        response = httpx.post(
            f"{settings.ai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            json={
                "model": settings.ai_model,
                "messages": [m.model_dump() for m in messages],
                "temperature": request.temperature,
            },
            timeout=settings.ai_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return ChatResponse(reply=data["choices"][0]["message"]["content"], model=settings.ai_model)
    except httpx.HTTPStatusError as exc:
        raise ExternalServiceError(
            f"AI provider error {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise ExternalServiceError(f"AI provider is unavailable: {exc}") from exc


def complete(prompt: str, *, system: str | None = None, temperature: float = 0.7) -> str:
    """Шорткат для использования из других сервисов: complete("Придумай слоган для ...")."""
    request = ChatRequest(
        messages=[ChatMessage(role="user", content=prompt)], system=system, temperature=temperature
    )
    return chat(request).reply
