from fastapi import APIRouter, status

from app.core.db import DbSession
from app.features.checklists import service
from app.features.checklists.defaults import default_checklist_config
from app.features.checklists.schemas import (
    ChecklistConfig,
    ChecklistCreate,
    ChecklistRead,
    ChecklistUpdate,
)

router = APIRouter(prefix="/checklists", tags=["checklists"])


@router.get("", response_model=list[ChecklistRead])
def list_checklists(db: DbSession):
    service.ensure_default(db)
    return service.list_checklists(db)


@router.get("/active", response_model=ChecklistRead)
def get_active(db: DbSession):
    return service.get_active(db)


@router.get("/default-config", response_model=ChecklistConfig)
def get_default_config():
    """Шаблон стартовой конфигурации — удобно для кнопки «Сбросить к базовому»."""
    return default_checklist_config()


@router.get("/{checklist_id}", response_model=ChecklistRead)
def get_checklist(checklist_id: int, db: DbSession):
    return service.get_checklist(db, checklist_id)


@router.post("", response_model=ChecklistRead, status_code=status.HTTP_201_CREATED)
def create_checklist(data: ChecklistCreate, db: DbSession):
    return service.create_checklist(db, data)


@router.put("/{checklist_id}", response_model=ChecklistRead)
def update_checklist(checklist_id: int, data: ChecklistUpdate, db: DbSession):
    return service.update_checklist(db, checklist_id, data)


@router.post("/{checklist_id}/activate", response_model=ChecklistRead)
def activate_checklist(checklist_id: int, db: DbSession):
    return service.activate_checklist(db, checklist_id)


@router.delete("/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_checklist(checklist_id: int, db: DbSession):
    service.delete_checklist(db, checklist_id)
