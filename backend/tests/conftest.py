import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://forge:test@localhost:5433/forge")
os.environ.setdefault("EPICWING_SECRET_KEY", "x" * 48)
os.environ.setdefault("EPICWING_ENCRYPTION_KEY", "test")
os.environ.setdefault("EPICWING_SCHEDULER", "0")
os.environ.setdefault("EPICWING_TIMEZONE", "UTC")
os.environ["EPICWING_ENV"] = "development"  # Tests always use dev mode

import pytest  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import passwords  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.security.ratelimit import (  # noqa: E402
    enroll_limiter,
    login_email_limiter,
    login_ip_limiter,
    password_change_limiter,
    totp_limiter,
)

TEST_PASSWORD = "correct-horse-battery"

# Der Original-Hasher mit den Produktionsparametern, bevor die Fixture ihn ersetzt.
PRODUCTION_PASSWORD_HASHER = passwords._hasher


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Argon2 ist absichtlich teuer; in Tests reichen Minimalparameter. monkeypatch
    # stellt den Produktions-Hasher nach jedem Test automatisch wieder her.
    monkeypatch.setattr(
        passwords,
        "_hasher",
        PasswordHasher(time_cost=1, memory_cost=8, parallelism=1),
    )


@pytest.fixture
def production_password_hasher() -> PasswordHasher:
    return PRODUCTION_PASSWORD_HASHER


@pytest.fixture
def db_session():
    # SQLite im Speicher: schnell und ohne laufende Datenbank.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    # SQLite setzt Fremdschlüssel (ON DELETE CASCADE) nur mit diesem Pragma durch.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    login_ip_limiter.clear()
    login_email_limiter.clear()
    password_change_limiter.clear()
    totp_limiter.clear()
    enroll_limiter.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user(db_session):
    account = User(
        email="admin@example.test",
        password_hash=hash_password(TEST_PASSWORD),
        is_admin=True,
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def credentials(user):
    return {"email": user.email, "password": TEST_PASSWORD}
