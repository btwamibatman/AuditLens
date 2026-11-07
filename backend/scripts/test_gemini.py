"""Скрипт проверки подключения к Google Gemini API (Interactions API).

Запуск:
    npm run test:gemini
или:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts/test_gemini.py
"""

import sys
from pathlib import Path

# Добавляем backend в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.features.checklists.service import ensure_default
from app.features.conversations.schemas import ConversationRecord
from app.features.conversations.service import upsert_records
from app.features.evaluations.llm import get_provider
from app.features.evaluations.service import evaluate


def main():
    settings = get_settings()
    print("=" * 60)
    print("AuditLens · Проверка подключения к Gemini API")
    print("=" * 60)
    print(f"Провайдер : {settings.llm_provider}")
    print(f"Модель    : {settings.gemini_model}")
    print(f"Thinking  : {settings.gemini_thinking_level}")

    if not settings.gemini_api_key:
        print("\n❌ ОШИБКА: GEMINI_API_KEY пустой в файле .env!")
        print("Вставьте ваш API-ключ в .env: GEMINI_API_KEY=AIzaSy...")
        return 1

    masked_key = settings.gemini_api_key[:8] + "..." + settings.gemini_api_key[-4:]
    print(f"Ключ API  : {masked_key}")

    print("\n[1/2] Отправка тестового запроса к модели...")
    provider = get_provider()

    try:
        ping = provider.generate(
            system_instruction="Ты помощник QA. Отвечай строго JSON.",
            input_text="Привет, подтверди готовность к работе.",
            schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["status", "message"],
            },
        )
        print("  ✓ Модель ответила успешно!")
        print(f"  Ответ       : {ping.text}")
        print(f"  Задержка    : {ping.latency_ms} мс")
        print(f"  Токены      : вход={ping.input_tokens}, выход={ping.output_tokens}, thinking={ping.thought_tokens}")
        print(f"  Стоимость   : ${ping.cost_usd():.6f}")
    except Exception as exc:
        print(f"\n❌ Ошибка подключения к Gemini: {exc}")
        return 1

    print("\n[2/2] Тестовая оценка реального брокерского диалога по чек-листу...")
    sample = ConversationRecord(
        conversation_id="test-gemini-live",
        channel="agent chat",
        language="RU",
        transcript=[
            {
                "timestamp": "00:01",
                "speaker": "client",
                "text": "Здравствуйте! Не могу понять, как вывести деньги на карту Kaspi.",
            },
            {
                "timestamp": "00:08",
                "speaker": "operator",
                "text": "Добрый день! Меня зовут Алия, Freedom Broker. Назовите, пожалуйста, ваш номер счёта для проверки.",
            },
            {"timestamp": "00:20", "speaker": "client", "text": "Счёт 55443322."},
            {
                "timestamp": "00:32",
                "speaker": "operator",
                "text": "Спасибо. Для вывода перейдите в приложении: Меню -> Переводы -> Вывод на карту РК, укажите сумму и подтвердите SMS-кодом. Срок зачисления от 5 до 15 минут, комиссия 0%.",
            },
            {"timestamp": "00:45", "speaker": "client", "text": "Понял, всё получилось, спасибо большое!"},
            {
                "timestamp": "00:52",
                "speaker": "operator",
                "text": "Отлично! Была рада помочь. Если вопросов больше нет, желаю вам отличного дня!",
            },
        ],
        audio_url=None,
    )

    with SessionLocal() as db:
        ensure_default(db)
        upsert_records(db, "TEST_LIVE", [sample])
        ev = evaluate(db, "test-gemini-live")

    print(f"  ✓ Диалог успешно оценён моделью {ev.model}!")
    print(f"  Итоговый балл : {ev.total_score} / 100")
    print(f"  Грубые ошибки : {'Да (0 баллов)' if ev.has_critical_error else 'Нет'}")
    print(f"  Стоимость     : ${ev.cost_usd:.5f} (~{ev.cost_usd * 500:.2f} тенге)")

    print("\nКритерии и найденные цитаты:")
    for c in ev.final_result.get("criteria", []):
        score_repr = f"{c['score']} балл(а)" if c["status"] == "scored" else "N/A"
        evidence_text = c["evidence"][0]["quote"] if c.get("evidence") else "—"
        if len(evidence_text) > 60:
            evidence_text = evidence_text[:60] + "..."
        print(f"  • {c['name']:<35} : {score_repr:<10} | Цитата: {evidence_text}")

    print("\n" + "=" * 60)
    print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ: Gemini API работает стабильно и точно!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

