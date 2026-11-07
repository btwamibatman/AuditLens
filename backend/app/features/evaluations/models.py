from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Evaluation(TimestampMixin, Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    checklist_id: Mapped[int | None] = mapped_column(
        ForeignKey("checklists.id", ondelete="SET NULL"), nullable=True, index=True
    )
    checklist_version: Mapped[int] = mapped_column(Integer, default=1)
    # Полная копия чек-листа на момент оценки: результат воспроизводим после правок чек-листа
    checklist_snapshot: Mapped[dict] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # done|failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str] = mapped_column(String(100), default="")
    # ai_result — исходная оценка модели; final_result — после решений по апелляциям
    ai_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_critical_error: Mapped[bool] = mapped_column(Boolean, default=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    thought_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)  # для отладки промпта
