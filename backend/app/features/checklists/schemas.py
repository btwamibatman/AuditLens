"""Конфигурация чек-листа.
Это единственный источник правды и для промпта LLM, и для подсчёта баллов.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnswerType = Literal["binary", "scale"]
RoundingMode = Literal["half_up", "floor", "ceil", "none"]
CriticalPolicy = Literal["zero_total", "flag_only"]


class ScaleLevel(BaseModel):
    """Описание одного уровня шкалы — помогает модели калиброваться под эталон."""

    value: int
    description: str


class Criterion(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$", description="Стабильный машинный ID")
    name: str = Field(min_length=1, max_length=200)
    section: str | None = Field(default=None, description="Секция для промежуточных итогов")
    description: str = Field(min_length=1, description="Что проверяем (формулировка для модели)")
    weight: float = Field(ge=0)
    answer_type: AnswerType = "binary"
    # Для binary шкала всегда 0..1 (0 = нет, 1 = да)
    scale_min: int = 0
    scale_max: int = 1
    scale_levels: list[ScaleLevel] = Field(default_factory=list)
    na_allowed: bool = False
    na_rule: str | None = Field(default=None, description="Когда критерий считается N/A")
    # Грубая ошибка: нарушение отмечается отдельно и может обнулить итог (см. critical_policy)
    is_critical: bool = False
    critical_rule: str | None = None
    # Канал, к которому применим критерий: chat, call или оба. Иначе — авто N/A.
    channels: list[Literal["chat", "call"]] = Field(default_factory=lambda: ["chat", "call"])
    enabled: bool = True

    @model_validator(mode="after")
    def _check_scale(self) -> "Criterion":
        if self.answer_type == "binary":
            self.scale_min, self.scale_max = 0, 1
        if self.scale_max <= self.scale_min:
            raise ValueError(f"{self.id}: scale_max must be greater than scale_min")
        if self.na_allowed and not self.na_rule:
            raise ValueError(f"{self.id}: na_rule is required when na_allowed=true")
        if self.is_critical and not self.critical_rule:
            raise ValueError(f"{self.id}: critical_rule is required when is_critical=true")
        return self


class ScoringRules(BaseModel):
    total_scale: float = Field(default=100, gt=0, description="Итог в процентах (0..100)")
    rounding: RoundingMode = "half_up"
    rounding_digits: int = Field(default=0, ge=0, le=4)
    critical_policy: CriticalPolicy = "zero_total"


class ChecklistConfig(BaseModel):
    criteria: list[Criterion] = Field(min_length=1)
    scoring: ScoringRules = Field(default_factory=ScoringRules)
    # Доп. инструкции для модели (общие правила компании, тон, контекст бизнеса)
    evaluator_notes: str = ""
    explanation_language: str = "ru"

    @model_validator(mode="after")
    def _unique_ids(self) -> "ChecklistConfig":
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion ids must be unique")
        return self

    @property
    def active_criteria(self) -> list[Criterion]:
        return [c for c in self.criteria if c.enabled]


class ChecklistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    config: ChecklistConfig


class ChecklistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    config: ChecklistConfig | None = None


class ChecklistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    version: int
    is_active: bool
    config: ChecklistConfig
    created_at: datetime
    updated_at: datetime
