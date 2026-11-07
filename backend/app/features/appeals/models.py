from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Appeal(TimestampMixin, Base):
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), index=True
    )
    criterion_id: Mapped[str] = mapped_column(String(50), index=True)

    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # pending|confirmed|overturned
    comment: Mapped[str] = mapped_column(Text)  # обоснование оператора / пользователя

    # Решение проверяющего
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "confirm" | "change"
    new_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_is_na: Mapped[bool | None] = mapped_column(nullable=True)
    new_critical_violation: Mapped[bool | None] = mapped_column(nullable=True)
