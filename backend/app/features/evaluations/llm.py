"""LLM-провайдеры за единым интерфейсом. Сейчас: Gemini (Interactions API) и mock.

Добавить другой провайдер (локальная модель, OpenAI-совместимый API) = реализовать generate()
и зарегистрировать в get_provider(). Остальной пайплайн не меняется.
"""

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import ExternalServiceError

log = logging.getLogger(__name__)

# Ошибки, на которых повтор бесполезен (неверный ключ, модель, запрос)
_NON_RETRYABLE_STATUS = {400, 401, 403, 404}


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    latency_ms: int = 0

    def cost_usd(self) -> float:
        s = get_settings()
        billed_output = self.output_tokens + self.thought_tokens
        return (
            self.input_tokens * s.llm_price_input_per_1m + billed_output * s.llm_price_output_per_1m
        ) / 1_000_000


class LLMProvider(Protocol):
    name: str

    def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult: ...


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, thinking_level: str, timeout: float):
        from google import genai  # импорт здесь: mock-режим работает без SDK

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.thinking_level = thinking_level
        self.timeout = timeout

    def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult:
        started = time.perf_counter()
        interaction = self._client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=input_text,
            response_format={"type": "text", "mime_type": "application/json", "schema": schema},
            generation_config={"thinking_level": self.thinking_level, "max_output_tokens": 16384},
            store=False,  # не храним диалоги клиентов на стороне провайдера
            timeout=self.timeout,
        )
        latency = int((time.perf_counter() - started) * 1000)
        text = interaction.output_text or ""
        usage = getattr(interaction, "usage", None)
        return LLMResult(
            text=text,
            model=self.model,
            input_tokens=getattr(usage, "total_input_tokens", None) or 0,
            output_tokens=getattr(usage, "total_output_tokens", None) or 0,
            thought_tokens=getattr(usage, "total_thought_tokens", None) or 0,
            latency_ms=latency,
        )


class MockProvider:
    """Офлайн-заглушка: без ключа и сети. Нужна для разработки UI и тестов, НЕ для оценки."""

    name = "mock"
    model = "mock"

    def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult:
        ids = schema["properties"]["criteria"]["items"]["properties"]["criterion_id"]["enum"]
        lines = [ln for ln in input_text.splitlines() if ln.startswith("[#")]
        operator = next((ln for ln in lines if " OPERATOR: " in ln), lines[0] if lines else "")
        idx = int(operator[2 : operator.index("]")]) if operator else 0
        quote = operator.split(": ", 1)[-1][:120] if operator else ""
        payload = {
            "criteria": [
                {
                    "criterion_id": cid,
                    "applicable": True,
                    "na_reason": "",
                    "score": 0,
                    "critical_violation": False,
                    "explanation": "MOCK: оценка-заглушка, LLM не вызывалась.",
                    "evidence": [{"message_index": idx, "quote": quote}],
                }
                for cid in ids
            ],
            "summary": "MOCK: задайте GEMINI_API_KEY в .env для реальной оценки.",
        }
        return LLMResult(text=json.dumps(payload, ensure_ascii=False), model="mock")


@lru_cache
def get_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "mock" or not s.gemini_api_key:
        log.warning("LLM provider: mock (GEMINI_API_KEY is empty or LLM_PROVIDER=mock)")
        return MockProvider()
    return GeminiProvider(
        api_key=s.gemini_api_key,
        model=s.gemini_model,
        thinking_level=s.gemini_thinking_level,
        timeout=s.llm_timeout_seconds,
    )


def generate_with_retry(
    provider: LLMProvider, *, system_instruction: str, input_text: str, schema: dict
) -> tuple[LLMResult, int]:
    """Вызов с экспоненциальным backoff. Возвращает (результат, число_попыток)."""
    attempts = get_settings().llm_max_retries
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return (
                provider.generate(
                    system_instruction=system_instruction, input_text=input_text, schema=schema
                ),
                attempt,
            )
        except Exception as exc:  # noqa: BLE001 — SDK бросает разные типы
            last_exc = exc
            status = _status_code(exc)
            log.warning(
                "LLM call failed (attempt %s/%s, status=%s): %s", attempt, attempts, status, exc
            )
            if status in _NON_RETRYABLE_STATUS or attempt == attempts:
                break
            time.sleep(min(2**attempt, 30))
    raise ExternalServiceError(f"LLM call failed: {last_exc}")
