import importlib
import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import User
from app.security.passwords import hash_password
from tests.conftest import TEST_PASSWORD
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login
from tests.test_server_power import FakeBroker

URL = os.environ.get("RACE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="needs RACE_DATABASE_URL (real PostgreSQL)")


@pytest.fixture
def pg():
    # Tabellen werden geloescht: nur gegen eine Datenbank namens "race"
    assert URL and URL.rstrip("/").endswith("/race"), "refusing to wipe a database not named race"
    engine = create_engine(URL, pool_size=20, max_overflow=20)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_parallel_creates_respect_the_memory_limit(pg, monkeypatch):
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", FakeBroker())
    with pg() as session:
        admin = User(
            email="admin@example.test", password_hash=hash_password(TEST_PASSWORD), is_admin=True
        )
        session.add(admin)
        session.commit()
    client = TestClient(app)
    headers = _login(client, admin)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run {{SERVER_PORT}}")
    allocations = make_allocations(client, headers, node_id, 25001, 25012)
    patched = client.patch(f"/api/nodes/{node_id}", json={"ram_limit_mb": 1024}, headers=headers)
    assert patched.status_code == 200, patched.text

    results: list[int] = []

    def create(i: int) -> None:
        body = {
            "name": f"Game {i}",
            "owner_id": str(admin.id),
            "node_id": node_id,
            "egg_id": egg_id,
            "allocation_id": allocations[i],
            "memory_mb": 512,
        }
        results.append(client.post("/api/servers", json=body, headers=headers).status_code)

    threads = [threading.Thread(target=create, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("\nAntworten:", sorted(results))
    assert results.count(201) == 2, sorted(results)
