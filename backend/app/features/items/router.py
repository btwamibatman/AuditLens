"""HTTP-слой: валидация входа, вызов сервиса, сериализация ответа. Логики здесь нет."""

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.schemas import Page
from app.features.items import service
from app.features.items.schemas import ItemCreate, ItemRead, ItemStatus, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=Page[ItemRead])
def list_items(
    db: DbSession,
    q: str | None = None,
    status: ItemStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items, total = service.list_items(db, q=q, status=status, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(data: ItemCreate, db: DbSession):
    return service.create_item(db, data)


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, db: DbSession):
    return service.get_item(db, item_id)


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(item_id: int, data: ItemUpdate, db: DbSession):
    return service.update_item(db, item_id, data)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, db: DbSession):
    service.delete_item(db, item_id)
