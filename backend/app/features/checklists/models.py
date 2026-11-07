from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Checklist(TimestampMixin, Base):
    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # Растёт при каждом изменении config — оценки хранят snapshot и номер версии
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    config: Mapped[dict] = mapped_column(JSON)
