"""Бизнес-логика. Принимает Session и схемы, возвращает модели. Про HTTP ничего не знает."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.features.items.models import Item
from app.features.items.schemas import ItemCreate, ItemUpdate


def list_items(
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Item], int]:
    stmt = select(Item)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Item.title.ilike(pattern), Item.description.ilike(pattern)))
    if status:
        stmt = stmt.where(Item.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Item.id.desc()).limit(limit).offset(offset)).all()
    return list(items), total


def get_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise NotFoundError(f"Item {item_id} not found")
    return item


def create_item(db: Session, data: ItemCreate) -> Item:
    item = Item(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, item_id: int, data: ItemUpdate) -> Item:
    item = get_item(db, item_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> None:
    item = get_item(db, item_id)
    db.delete(item)
    db.commit()
