from fastapi import APIRouter, status

from app.core.db import DbSession
from app.features.checklists import service as checklist_service
from app.features.conversations import service as conversation_service
from app.features.evaluations import service
from app.features.evaluations.schemas import (
    BatchRequest,
    BatchStatus,
    EvaluateRequest,
    EvaluationRead,
    EvaluationSummary,
    PromptPreview,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post(
    "",
    response_model=EvaluationRead,
    status_code=status.HTTP_201_CREATED,
    responses={429: {"description": "Все слоты оценки заняты; повторите запрос позже."}},
)
def evaluate(data: EvaluateRequest, db: DbSession):
    """Синхронная оценка одного диалога (обычно 5–30 c в зависимости от модели)."""
    return service.evaluate(db, data.conversation_id, data.checklist_id)


@router.post(
    "/batch",
    response_model=BatchStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"description": "Пакетная обработка уже идёт."}},
)
def start_batch(data: BatchRequest, db: DbSession):
    """Фоновая оценка набора (напр. контрольных диалогов). Прогресс: GET /batch/{id}."""
    ids, checklist_id = service.resolve_batch_targets(db, data)
    pinned = service._snapshot_checklist(checklist_id, db=db)
    return service.start_batch_job(ids, checklist_id, pinned_checklist=pinned)


@router.get("/batch/{job_id}", response_model=BatchStatus)
def batch_status(job_id: str):
    return service.get_batch_job(job_id)


@router.get("/prompt-preview", response_model=PromptPreview)
def prompt_preview(conversation_id: str, db: DbSession, checklist_id: int | None = None):
    """Показывает ровно тот промпт и схему, что уйдут в LLM — прозрачность для жюри и отладки."""
    conv = conversation_service.get_conversation(db, conversation_id)
    checklist = (
        checklist_service.get_checklist(db, checklist_id)
        if checklist_id
        else checklist_service.get_active(db)
    )
    return service.build_prompt(conv, checklist_service.parse_config(checklist))


@router.get("", response_model=list[EvaluationSummary])
def list_evaluations(
    db: DbSession,
    conversation_id: str | None = None,
    checklist_id: int | None = None,
    checklist_version: int | None = None,
    dataset_group: str | None = None,
):
    return service.list_evaluations(
        db,
        conversation_id=conversation_id,
        checklist_id=checklist_id,
        checklist_version=checklist_version,
        dataset_group=dataset_group,
    )


@router.get("/{evaluation_id}", response_model=EvaluationRead)
def get_evaluation(evaluation_id: int, db: DbSession):
    return service.get_evaluation(db, evaluation_id)
