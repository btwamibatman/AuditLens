"""Подключение к БД, базовый класс моделей и зависимость get_db для роутов."""

import importlib
import pkgutil
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, MetaData, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings

# Единые имена constraints нужны, чтобы Alembic корректно генерировал миграции,
# особенно в SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Добавляет created_at / updated_at. Использование: class Foo(TimestampMixin, Base)."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        path = url.split("///", 1)[-1] if "///" in url else ""
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Используйте в роутах:  def handler(db: DbSession): ...
DbSession = Annotated[Session, Depends(get_db)]


def import_all_models() -> None:
    """Импортирует app/features/*/models.py, чтобы Alembic видел все таблицы.

    Новую фичу никуда регистрировать не нужно — достаточно создать в ней models.py.
    """
    import app.features as features

    for module in pkgutil.iter_modules(features.__path__):
        if not module.ispkg:
            continue
        name = f"app.features.{module.name}.models"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
