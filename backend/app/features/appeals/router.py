from fastapi import APIRouter, status

from app.core.db import DbSession
from app.features.appeals import service
from app.features.appeals.schemas import AppealCreate, AppealRead, AppealReview
from app.features.evaluations.schemas import EvaluationRead

router = APIRouter(prefix="/appeals", tags=["appeals"])


@router.post("", response_model=AppealRead, status_code=status.HTTP_201_CREATED)
def create_appeal(data: AppealCreate, db: DbSession):
    """Подать апелляцию по спорному критерию."""
    return service.create_appeal(db, data)


@router.post("/{appeal_id}/review", response_model=EvaluationRead)
def review_appeal(appeal_id: int, data: AppealReview, db: DbSession):
    """Решение проверяющего: confirm (подтвердить AI) или change (пересчитать итог)."""
    _appeal, evaluation = service.review_appeal(db, appeal_id, data)
    return evaluation


@router.get("", response_model=list[AppealRead])
def list_appeals(db: DbSession, evaluation_id: int | None = None, status: str | None = None):
    return service.list_appeals(db, evaluation_id=evaluation_id, status=status)


@router.get("/{appeal_id}", response_model=AppealRead)
def get_appeal(appeal_id: int, db: DbSession):
    return service.get_appeal(db, appeal_id)
