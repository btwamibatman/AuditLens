from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.features.auth.models import User
from app.features.auth.schemas import RegisterRequest

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.secret_key, ALGORITHM)


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def register(db: Session, data: RegisterRequest) -> User:
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("User with this email already exists")
    user = User(email=email, name=data.name, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Wrong email or password")
    return user


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    return user
