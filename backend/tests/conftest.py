import os

# Настройки для тестов задаём ДО импорта приложения (переменные окружения важнее .env).
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite://",
        "ENABLE_AUTH": "true",
        "ENABLE_UPLOADS": "false",
        "ENABLE_AI": "true",
        "AI_API_KEY": "",
        "FRONTEND_DIST": "./__no_dist__",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.db import Base, get_db, import_all_models  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    import_all_models()
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with TestSession() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
