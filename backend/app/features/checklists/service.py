from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.features.checklists.defaults import DEFAULT_CHECKLIST_NAME, default_checklist_config
from app.features.checklists.models import Checklist
from app.features.checklists.schemas import ChecklistConfig, ChecklistCreate, ChecklistUpdate


def list_checklists(db: Session) -> list[Checklist]:
    return list(db.scalars(select(Checklist).order_by(Checklist.id)))


def get_checklist(db: Session, checklist_id: int) -> Checklist:
    checklist = db.get(Checklist, checklist_id)
    if checklist is None:
        raise NotFoundError(f"Checklist {checklist_id} not found")
    return checklist


def get_active(db: Session) -> Checklist:
    """Активный чек-лист; если в БД пусто — создаёт стартовый."""
    checklist = db.scalar(select(Checklist).where(Checklist.is_active.is_(True)))
    if checklist is not None:
        return checklist
    if db.scalar(select(Checklist.id).limit(1)) is not None:
        raise AppError("No active checklist. Activate one via POST /checklists/{id}/activate")
    return ensure_default(db)


def ensure_default(db: Session) -> Checklist:
    existing = db.scalar(select(Checklist).order_by(Checklist.id).limit(1))
    if existing is not None:
        return existing
    checklist = Checklist(
        name=DEFAULT_CHECKLIST_NAME,
        description="Стартовая конфигурация из 8 критериев",
        config=default_checklist_config().model_dump(mode="json"),
        is_active=True,
    )
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist


def create_checklist(db: Session, data: ChecklistCreate) -> Checklist:
    checklist = Checklist(
        name=data.name,
        description=data.description,
        config=data.config.model_dump(mode="json"),
        is_active=False,
    )
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist


def update_checklist(db: Session, checklist_id: int, data: ChecklistUpdate) -> Checklist:
    checklist = get_checklist(db, checklist_id)
    if data.name is not None:
        checklist.name = data.name
    if data.description is not None:
        checklist.description = data.description
    if data.config is not None:
        checklist.config = data.config.model_dump(mode="json")
        checklist.version += 1
    db.commit()
    db.refresh(checklist)
    return checklist


def activate_checklist(db: Session, checklist_id: int) -> Checklist:
    checklist = get_checklist(db, checklist_id)
    db.execute(update(Checklist).values(is_active=False))
    checklist.is_active = True
    db.commit()
    db.refresh(checklist)
    return checklist


def delete_checklist(db: Session, checklist_id: int) -> None:
    checklist = get_checklist(db, checklist_id)
    if checklist.is_active:
        raise AppError("Cannot delete the active checklist")
    db.delete(checklist)
    db.commit()


def parse_config(checklist: Checklist) -> ChecklistConfig:
    return ChecklistConfig.model_validate(checklist.config)
