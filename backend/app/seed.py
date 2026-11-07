"""Инициализация базовых данных: python -m app.seed (или npm run db:seed из корня).

Гарантирует наличие стартового чек-листа CQA (8 критериев ТЗ), если таблица чек-листов пуста.
Существующие чек-листы, диалоги и оценки не перезаписываются.
"""

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.features.checklists.service import ensure_default
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
        checklist = ensure_default(db)
        print(f"Active/default CQA checklist ready: id={checklist.id} v{checklist.version}")
        if db.scalar(select(func.count()).select_from(Item)):
            return
        db.add_all(Item(title=t, description=d, status=s) for t, d, s in DEMO_ITEMS)
        db.commit()


if __name__ == "__main__":
    seed()
