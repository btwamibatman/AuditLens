"""Демо-данные: python -m app.seed  (или npm run db:seed из корня).

Заполняйте реалистичными данными под идею — это сильно улучшает демо.
"""

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.features.items.models import Item

DEMO_ITEMS = [
    (
        "Сформулировать проблему",
        "Кто пользователь и какую боль решаем — одним предложением.",
        "done",
    ),
    ("Собрать MVP", "Один ключевой сценарий, который работает от начала до конца.", "in_progress"),
    ("Подключить AI", "ENABLE_AI=true и ключ в .env — и можно звать complete().", "todo"),
    ("Подготовить демо", "Сценарий на 3 минуты, данные заранее в базе, запасное видео.", "todo"),
]


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Item)):
            print("Items already exist — skipping seed.")
            return
        db.add_all(Item(title=t, description=d, status=s) for t, d, s in DEMO_ITEMS)
        db.commit()
        print(f"Seeded {len(DEMO_ITEMS)} items.")


if __name__ == "__main__":
    seed()
