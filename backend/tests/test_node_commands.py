import uuid

import pytest
from sqlalchemy import select

from app.agentlink.commands import AgentOffline, broker
from app.agentlink.protocol import CommandResult
from app.models import AuditLog
from tests.test_agent_ws import WS_URL, _enroll_node, _login_agent
from tests.test_nodes_detail import _create, _login

CREATE = {
    "name": "web-1",
    "image": "nginx:1.27",
    "ports": [{"host": 25001, "container": 80, "proto": "tcp"}],
    "env": {"TOKEN": "SECRET"},
    "memory_mb": 256,
    "cpus": 0.5,
}


@pytest.fixture
def agent(monkeypatch):
    state = {
        "calls": [],
        "exc": None,
        "result": CommandResult(type="result", id="x", ok=True, data={"id": "abc123"}),
    }

    async def fake_send(node_id, action, params, timeout=90):
        state["calls"].append((node_id, action, params))
        if state["exc"] is not None:
            raise state["exc"]
        return state["result"]

    monkeypatch.setattr(broker, "send", fake_send)
    return state


def _post(client, node_id, headers, action="container.start", params=None):
    body = {"action": action, "params": params if params is not None else {"name": "web-1"}}
    return client.post(f"/api/nodes/{node_id}/commands", json=body, headers=headers)


def _audit_entries(db_session):
    db_session.expire_all()
    return db_session.scalars(select(AuditLog).where(AuditLog.action == "node.command")).all()


def test_command_is_sent_and_audited(client, db_session, user, agent):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        response = _post(client, node_id, headers, "container.create", CREATE)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {"id": "abc123"}, "error": None}
    assert agent["calls"][0][1:] == ("container.create", CREATE)
    entry = _audit_entries(db_session)[0]
    assert entry.details["action"] == "container.create"
    assert entry.details["container"] == "web-1"
    assert entry.details["outcome"] == "ok"
    assert "SECRET" not in str(entry.details)


def test_agent_error_is_passed_on(client, db_session, user, agent):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    agent["result"] = CommandResult(type="result", id="x", ok=False, error="boom")
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        response = _post(client, node_id, headers)
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "boom"
    assert _audit_entries(db_session)[0].details["outcome"] == "failed"


def test_lost_agent_gives_409(client, db_session, user, agent):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    agent["exc"] = AgentOffline()
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        assert _post(client, node_id, headers).status_code == 409
    assert _audit_entries(db_session)[0].details["outcome"] == "offline"


def test_timeout_gives_504(client, db_session, user, agent):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    agent["exc"] = TimeoutError()
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        assert _post(client, node_id, headers).status_code == 504
    assert _audit_entries(db_session)[0].details["outcome"] == "timeout"


def test_node_without_connection_gives_409(client, user, agent):
    node_id, _key = _enroll_node(client, user)
    assert _post(client, node_id, _login(client, user)).status_code == 409
    assert not agent["calls"]


def test_pending_node_gives_409(client, user, agent):
    headers = _login(client, user)
    node_id = _create(client, headers)
    assert _post(client, node_id, headers).status_code == 409
    assert not agent["calls"]


def test_unknown_node_gives_404(client, user, agent):
    headers = _login(client, user)
    assert _post(client, uuid.uuid4(), headers).status_code == 404


def test_csrf_token_is_required(client, user, agent):
    node_id, key = _enroll_node(client, user)
    _login(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        assert _post(client, node_id, {}).status_code == 403
    assert not agent["calls"]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "shell.run", "params": {"name": "web-1"}},
        {"action": "container.start", "params": {"name": "web-1", "force": True}},
        {"action": "container.start", "params": {"name": "-rm"}},
        {"action": "container.remove", "params": {}},
        {"action": "container.create", "params": {k: v for k, v in CREATE.items() if k != "cpus"}},
        {"action": "container.start", "params": {"name": "web-1"}, "extra": 1},
    ],
)
def test_invalid_commands_are_rejected(client, user, agent, body):
    headers = _login(client, user)
    node_id = _create(client, headers)
    response = client.post(f"/api/nodes/{node_id}/commands", json=body, headers=headers)
    assert response.status_code == 422
    assert not agent["calls"]
