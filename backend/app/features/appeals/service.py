from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.features.appeals.models import Appeal
from app.features.appeals.schemas import AppealCreate, AppealReview
from app.features.checklists.schemas import ChecklistConfig
from app.features.evaluations.models import Evaluation
from app.features.evaluations.schemas import CriterionResult, EvaluationResult
from app.features.evaluations.scoring import compute_totals


def create_appeal(db: Session, data: AppealCreate) -> Appeal:
    evaluation = db.get(Evaluation, data.evaluation_id)
    if evaluation is None:
        raise NotFoundError(f"Evaluation {data.evaluation_id} not found")
    if evaluation.status != "done":
        raise AppError("Can only appeal a completed evaluation")

    criteria = (evaluation.final_result or {}).get("criteria", [])
    target = next((c for c in criteria if c["criterion_id"] == data.criterion_id), None)
    if target is None:
        raise NotFoundError(f"Criterion {data.criterion_id} not found in this evaluation")

    existing = db.scalar(
        select(Appeal).where(
            Appeal.evaluation_id == data.evaluation_id,
            Appeal.criterion_id == data.criterion_id,
            Appeal.status == "pending",
        )
    )
    if existing is not None:
        raise AppError(f"Pending appeal already exists for criterion {data.criterion_id}")

    appeal = Appeal(
        evaluation_id=data.evaluation_id,
        criterion_id=data.criterion_id,
        comment=data.comment,
        status="pending",
    )
    db.add(appeal)
    db.commit()
    db.refresh(appeal)
    return appeal


def review_appeal(db: Session, appeal_id: int, review: AppealReview) -> tuple[Appeal, Evaluation]:
    appeal = db.get(Appeal, appeal_id)
    if appeal is None:
        raise NotFoundError(f"Appeal {appeal_id} not found")
    if appeal.status != "pending":
        raise AppError("This appeal has already been reviewed")

    evaluation = db.get(Evaluation, appeal.evaluation_id)
    if evaluation is None:
        raise NotFoundError(f"Evaluation {appeal.evaluation_id} not found")

    appeal.reviewer_comment = review.reviewer_comment
    appeal.decision = review.decision
    appeal.status = "confirmed" if review.decision == "confirm" else "overturned"

    if review.decision == "change":
        appeal.new_score = review.new_score
        appeal.new_is_na = review.new_is_na
        appeal.new_critical_violation = review.new_critical_violation

        # Применяем изменение к final_result карточки и пересчитываем итоги
        current = EvaluationResult.model_validate(evaluation.final_result)
        config = ChecklistConfig.model_validate(evaluation.checklist_snapshot)
        updated_criteria: list[CriterionResult] = []
        for c in current.criteria:
            if c.criterion_id == appeal.criterion_id:
                c.status = "na" if review.new_is_na else "scored"
                c.score = None if review.new_is_na else review.new_score
                c.critical_violation = review.new_critical_violation
                c.source = "reviewer"
                c.explanation = f"ПЕРЕСМОТРЕН ПРО ВЕРЯЮЩИМ: {review.reviewer_comment}"
                if review.new_is_na:
                    c.na_reason = review.new_na_reason or review.reviewer_comment
            updated_criteria.append(c)

        recalculated = compute_totals(updated_criteria, config.scoring, current.summary)
        evaluation.final_result = recalculated.model_dump(mode="json")
        evaluation.total_score = recalculated.total
        evaluation.has_critical_error = recalculated.has_critical_error

    db.commit()
    db.refresh(appeal)
    db.refresh(evaluation)
    return appeal, evaluation


def list_appeals(
    db: Session, *, evaluation_id: int | None = None, status: str | None = None
) -> list[Appeal]:
    stmt = select(Appeal).order_by(Appeal.id.desc())
    if evaluation_id:
        stmt = stmt.where(Appeal.evaluation_id == evaluation_id)
    if status:
        stmt = stmt.where(Appeal.status == status)
    return list(db.scalars(stmt))


def get_appeal(db: Session, appeal_id: int) -> Appeal:
    appeal = db.get(Appeal, appeal_id)
    if appeal is None:
        raise NotFoundError(f"Appeal {appeal_id} not found")
    return appeal
