from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMEvidence(BaseModel):
    model_config = ConfigDict(strict=True)

    message_index: int
    quote: str


class LLMRange(BaseModel):
    model_config = ConfigDict(strict=True)

    from_index: int
    to_index: int


class LLMCriterionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    criterion_id: str
    applicable: bool
    na_reason: str = ""
    score: int
    critical_violation: bool
    explanation: str
    evidence: list[LLMEvidence]
    checked_range: LLMRange | None = None


class LLMEvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    criteria: list[LLMCriterionOutput]
    summary: str

ResultSource = Literal["ai", "auto", "reviewer"]


class Evidence(BaseModel):
    message_index: int
    quote: str
    timestamp: str = ""
    speaker: str = ""
    verified: bool = False 


class CheckedRange(BaseModel):
    from_index: int
    to_index: int
    from_timestamp: str = ""
    to_timestamp: str = ""


class CriterionResult(BaseModel):
    criterion_id: str
    name: str
    section: str | None = None
    answer_type: str
    weight: float
    scale_min: int
    scale_max: int
    is_critical: bool = False

    status: Literal["scored", "na"]
    score: int | None = None
    na_reason: str = ""
    critical_violation: bool = False
    explanation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    checked_range: CheckedRange | None = None

    # Заполняется scoring.compute_totals
    normalized: float | None = None  # 0..1
    effective_weight: float = 0  # вес после перераспределения N/A, в пунктах итоговой шкалы
    points: float = 0  # вклад в итог

    source: ResultSource = "ai"
    warnings: list[str] = Field(default_factory=list)


class SectionResult(BaseModel):
    section: str
    score: float | None  # в процентах; None если все критерии секции N/A
    points: float
    max_points: float


class EvaluationResult(BaseModel):
    criteria: list[CriterionResult]
    sections: list[SectionResult] = Field(default_factory=list)
    total_raw: float | None = None  # до учёта грубой ошибки и округления
    total_before_critical: float | None = None  # округлённый
    total: float | None = None  # финальный итог с учётом политики грубых ошибок
    has_critical_error: bool = False
    critical_criteria: list[str] = Field(default_factory=list)
    summary: str = ""


# ---------- API ----------


class EvaluateRequest(BaseModel):
    conversation_id: str
    checklist_id: int | None = None  # None = активный чек-лист


class BatchRequest(BaseModel):
    dataset_group: str | None = None
    conversation_ids: list[str] | None = None
    checklist_id: int | None = None
    only_missing: bool = False  # пропускать диалоги, уже оценённые этой версией чек-листа


class BatchStatus(BaseModel):
    job_id: str
    status: Literal["running", "done", "failed"]
    total: int
    done: int
    failed: int
    evaluation_ids: list[int] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    total_cost_usd: float = 0


class UsageInfo(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    cost_usd: float = 0
    latency_ms: int = 0
    attempts: int = 1


class EvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: str
    checklist_id: int | None
    checklist_version: int
    checklist_snapshot: dict | None = None
    status: str
    error: str | None
    model: str
    total_score: float | None
    has_critical_error: bool
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    cost_usd: float
    latency_ms: int
    ai_result: EvaluationResult | None
    final_result: EvaluationResult | None
    created_at: datetime


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: str
    checklist_id: int | None
    checklist_version: int
    status: str
    model: str
    total_score: float | None
    has_critical_error: bool
    cost_usd: float
    created_at: datetime


class PromptPreview(BaseModel):
    system_instruction: str
    input: str
    response_schema: dict
    llm_criteria: list[str]
    auto_na_criteria: list[str]
