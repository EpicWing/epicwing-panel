import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://forge:test@localhost:5432/forge")
os.environ.setdefault("FORGE_SECRET_KEY", "x" * 48)
os.environ.setdefault("FORGE_ENCRYPTION_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402


class _FakeSession:
    def execute(self, *_args, **_kwargs):
        return None


def test_health_ok():
    app.dependency_overrides[get_db] = lambda: _FakeSession()
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    app.dependency_overrides.clear()
