from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AppealStatus = Literal["pending", "confirmed", "overturned"]
Decision = Literal["confirm", "change"]


class AppealCreate(BaseModel):
    evaluation_id: int
    criterion_id: str
    comment: str = Field(min_length=1, max_length=2000)


class AppealReview(BaseModel):
    decision: Decision
    reviewer_comment: str = Field(min_length=1, max_length=2000)
    # Заполняется только если decision == "change":
    new_score: int | None = None
    new_is_na: bool = False
    new_na_reason: str = ""
    new_critical_violation: bool = False


class AppealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    evaluation_id: int
    criterion_id: str
    status: AppealStatus
    comment: str
    reviewer_comment: str | None
    decision: str | None
    new_score: int | None
    new_is_na: bool | None
    new_critical_violation: bool | None
    created_at: datetime
    updated_at: datetime
