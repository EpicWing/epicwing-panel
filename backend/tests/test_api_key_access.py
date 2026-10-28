import uuid
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import AuditLog
from app.security.apikeys import KeyContext, ServerAuth, get_server_auth
from app.security.server_access import ServerPermission, server_access
from app.services import audit
from tests.helpers import collect_routes
from tests.test_api_keys import _bearer, _create, _login

_ACCESS_DEP = "server_access.<locals>.dependency"


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def test_server_auth_is_only_used_together_with_server_access():
    allowed_alone = {("/api/servers", "GET")}
    through_access = 0
    bad = []
    for route in collect_routes(app):
        calls = list(_calls(route.dependant))
        if get_server_auth not in calls:
            continue
        via_access = any(getattr(c, "__qualname__", "") == _ACCESS_DEP for c in calls)
        through_access += via_access
        for method in sorted(route.methods or {"WS"}):
            if not via_access and (route.path, method) not in allowed_alone:
                bad.append(f"{method} {route.path}")
    assert not bad, bad
    # Schutz gegen Leerlauf: Der Test muss die Server-Routen wirklich sehen.
    assert through_access >= 10, through_access


@pytest.mark.parametrize(
    "permission", [ServerPermission.ACCESS_VIEW, ServerPermission.ACCESS_MANAGE]
)
def test_keys_cannot_touch_server_access(permission):
    context = KeyContext(user=None, session=None, key=None)
    with pytest.raises(HTTPException) as caught:
        server_access(permission)(uuid.uuid4(), context, None)
    assert caught.value.status_code == 403


def test_a_key_lists_servers_without_a_cookie(client, credentials):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    client.cookies.clear()
    reply = client.get("/api/servers", headers=_bearer(token))
    assert reply.status_code == 200, reply.text
    assert isinstance(reply.json(), list)


def test_a_key_cannot_create_servers(client, credentials):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    client.cookies.clear()
    reply = client.post("/api/servers", json={}, headers=_bearer(token))
    assert reply.status_code == 401


def test_audit_entries_mark_actions_done_with_a_key(client, credentials, db_session):
    headers = _login(client, credentials)
    token = _create(client, headers, name="bot")["token"]

    probe = FastAPI()

    @probe.post("/audited")
    def audited(auth: ServerAuth, db: Annotated[Session, Depends(get_db)]) -> dict:
        audit.record(db, "test.action", actor_id=auth.user.id)
        return {}

    probe.dependency_overrides[get_db] = lambda: db_session
    assert TestClient(probe).post("/audited", headers=_bearer(token)).status_code == 200

    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "test.action")).one()
    assert entry.details["via_api_key"]["name"] == "bot"
