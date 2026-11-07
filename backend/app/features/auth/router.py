from fastapi import APIRouter, status

from app.core.db import DbSession
from app.features.auth import service
from app.features.auth.deps import CurrentUser
from app.features.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user) -> TokenResponse:
    return TokenResponse(
        access_token=service.create_access_token(user.id), user=UserRead.model_validate(user)
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: DbSession):
    return _token_for(service.register(db, data))


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: DbSession):
    return _token_for(service.authenticate(db, data.email, data.password))


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user
