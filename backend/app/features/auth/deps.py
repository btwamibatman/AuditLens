"""Зависимости для защиты роутов.

    from app.features.auth.deps import CurrentUser

    @router.post("/secret")
    def secret(user: CurrentUser): ...
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.db import DbSession
from app.core.errors import UnauthorizedError
from app.features.auth import service
from app.features.auth.models import User

_bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def get_optional_user(db: DbSession, credentials: Credentials) -> User | None:
    if credentials is None:
        return None
    return service.get_user(db, service.decode_access_token(credentials.credentials))


def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise UnauthorizedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
