"""LLM-провайдеры за единым интерфейсом. Сейчас: Gemini (Interactions API) и mock.

Добавить другой провайдер (локальная модель, OpenAI-совместимый API) = реализовать generate()
и зарегистрировать в get_provider(). Остальной пайплайн не меняется.
"""

import inspect
import json
import logging
import threading
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


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return any(
        base.__name__.endswith(("TimeoutException", "TimeoutError"))
        for base in type(exc).__mro__
    )


def _extract_usage_tokens(usage: object) -> tuple[int, int, int]:
    """Извлекает (input, output, thought) по семантике SDK Usage без двойного учёта thinking."""
    if usage is None:
        return 0, 0, 0
    input_tokens = int(getattr(usage, "total_input_tokens", None) or 0)
    output_tokens = int(getattr(usage, "total_output_tokens", None) or 0)
    thought_tokens = int(getattr(usage, "total_thought_tokens", None) or 0)
    total_tokens = int(getattr(usage, "total_tokens", None) or 0)
    # Если провайдер включил thought_tokens внутрь total_output_tokens (так что
    # total_input_tokens + total_output_tokens уже дают total_tokens), вычитаем thought_tokens,
    # чтобы cost_usd() не учитывал thinking дважды.
    if (
        total_tokens > 0
        and thought_tokens > 0
        and input_tokens + output_tokens == total_tokens
        and output_tokens >= thought_tokens
    ):
        output_tokens -= thought_tokens
    return input_tokens, output_tokens, thought_tokens


def _extract_partial_result(exc: BaseException, model: str, latency_ms: int) -> LLMResult:
    existing = getattr(exc, "partial_result", None)
    if isinstance(existing, LLMResult):
        return existing
    usage = getattr(exc, "usage", None)
    if usage is None:
        partial_interaction = getattr(exc, "partial_interaction", None)
        usage = getattr(partial_interaction, "usage", None)
    inp, out, thought = _extract_usage_tokens(usage)
    return LLMResult(
        text="",
        model=model,
        input_tokens=inp,
        output_tokens=out,
        thought_tokens=thought,
        latency_ms=latency_ms,
    )


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, thinking_level: str, timeout: float):
        from google import genai  # импорт здесь: mock-режим работает без SDK
        from google.genai import types

        # Отключаем скрытые внутренние retry SDK (по умолчанию max_retries=4 в google-genai 3.0.0,
        # что умножало каждый таймаут/503 в 5 сетевых попыток поверх generate_with_retry).
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self.model = model
        self.thinking_level = thinking_level
        self.timeout = timeout

    def generate(
        self,
        *,
        system_instruction: str,
        input_text: str,
        schema: dict,
        timeout: float | None = None,
    ) -> LLMResult:
        effective_timeout = (
            self.timeout if timeout is None else max(0.001, min(self.timeout, timeout))
        )
        started = time.perf_counter()
        try:
            interaction = self._client.interactions.create(
                model=self.model,
                system_instruction=system_instruction,
                input=input_text,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
                generation_config={
                    "thinking_level": self.thinking_level,
                    "max_output_tokens": 16384,
                },
                store=False,  # не храним диалоги клиентов на стороне провайдера
                automatic_continuation=False,
                timeout=effective_timeout,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            exc.partial_result = _extract_partial_result(exc, self.model, latency)  # type: ignore[attr-defined]
            raise

        latency = int((time.perf_counter() - started) * 1000)
        text = interaction.output_text or ""
        inp, out, thought = _extract_usage_tokens(getattr(interaction, "usage", None))
        return LLMResult(
            text=text,
            model=self.model,
            input_tokens=inp,
            output_tokens=out,
            thought_tokens=thought,
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


def _accepts_timeout_kwarg(fn: object) -> bool:
    try:
        params = inspect.signature(fn).parameters  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return "timeout" in params


def _invoke_with_deadline(
    provider: LLMProvider,
    *,
    system_instruction: str,
    input_text: str,
    schema: dict,
    timeout: float,
) -> LLMResult:
    kwargs: dict = {
        "system_instruction": system_instruction,
        "input_text": input_text,
        "schema": schema,
    }
    if _accepts_timeout_kwarg(provider.generate):
        kwargs["timeout"] = timeout

    if getattr(provider, "name", "") == "mock":
        return provider.generate(**kwargs)

    box: dict[str, object] = {}
    started = time.perf_counter()

    def _target() -> None:
        try:
            box["result"] = provider.generate(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    worker = threading.Thread(target=_target, daemon=True, name="llm-call")
    worker.start()
    worker.join(timeout=max(0.001, timeout))
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if worker.is_alive():
        model_name = getattr(provider, "model", getattr(provider, "name", "unknown"))
        err = TimeoutError(
            f"LLM call timed out after {timeout:.2f}s "
            "(remote network request cancellation/billing is not guaranteed)"
        )
        err.partial_result = LLMResult(  # type: ignore[attr-defined]
            text="",
            model=model_name,
            latency_ms=elapsed_ms,
        )
        raise err

    if "error" in box:
        exc = box["error"]
        assert isinstance(exc, BaseException)
        model_name = getattr(provider, "model", getattr(provider, "name", "unknown"))
        if not isinstance(getattr(exc, "partial_result", None), LLMResult):
            exc.partial_result = _extract_partial_result(exc, model_name, elapsed_ms)  # type: ignore[attr-defined]
        raise exc

    result = box["result"]
    assert isinstance(result, LLMResult)
    if result.latency_ms <= 0 and elapsed_ms > 0:
        result.latency_ms = elapsed_ms
    return result


def generate_with_retry(
    provider: LLMProvider,
    *,
    system_instruction: str,
    input_text: str,
    schema: dict,
    deadline: float | None = None,
) -> tuple[LLMResult, int]:
    """Вызов с экспоненциальным backoff и общим дедлайном. Возвращает (результат, число_попыток)."""
    settings = get_settings()
    attempts = max(1, settings.llm_max_retries)
    overall_deadline = (
        deadline if deadline is not None else time.monotonic() + settings.llm_timeout_seconds
    )
    model_name = getattr(provider, "model", getattr(provider, "name", "unknown"))

    spent_input = 0
    spent_output = 0
    spent_thought = 0
    spent_latency = 0
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        remaining = overall_deadline - time.monotonic()
        if remaining <= 0:
            last_exc = TimeoutError(
                "LLM evaluation deadline exceeded "
                "(remote network request cancellation/billing is not guaranteed)"
            )
            break

        try:
            result = _invoke_with_deadline(
                provider,
                system_instruction=system_instruction,
                input_text=input_text,
                schema=schema,
                timeout=remaining,
            )
            result.input_tokens += spent_input
            result.output_tokens += spent_output
            result.thought_tokens += spent_thought
            result.latency_ms += spent_latency
            return result, attempt
        except Exception as exc:  # noqa: BLE001 — SDK бросает разные типы
            partial = getattr(exc, "partial_result", None)
            if isinstance(partial, LLMResult):
                spent_input += partial.input_tokens
                spent_output += partial.output_tokens
                spent_thought += partial.thought_tokens
                spent_latency += partial.latency_ms
            if _is_timeout_error(exc) and "cancellation" not in str(exc):
                exc = TimeoutError(
                    f"{exc} (remote network request cancellation/billing is not guaranteed)"
                )
            last_exc = exc
            status = _status_code(exc)
            log.warning(
                "LLM call failed (attempt %s/%s, status=%s): %s", attempt, attempts, status, exc
            )
            if (
                status in _NON_RETRYABLE_STATUS
                or attempt == attempts
                or _is_timeout_error(exc)
            ):
                break
            backoff = min(2**attempt, 30)
            if overall_deadline - time.monotonic() <= backoff:
                break
            time.sleep(backoff)

    err = ExternalServiceError(f"LLM call failed: {last_exc}")
    err.partial_result = LLMResult(  # type: ignore[attr-defined]
        text="",
        model=model_name,
        input_tokens=spent_input,
        output_tokens=spent_output,
        thought_tokens=spent_thought,
        latency_ms=spent_latency,
    )
    raise err
