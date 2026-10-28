import uuid

import pytest
from sqlalchemy import select

from app.agentlink.commands import AgentOffline, broker
from app.agentlink.protocol import CommandResult
from app.models import AuditLog
from tests.test_agent_ws import WS_URL, _enroll_node, _login_agent
from tests.test_nodes_detail import _login

GONE = "docker inspect: exit status 1: Error: No such object: ew-abc"


@pytest.fixture
def agent(monkeypatch):
    state = {
        "calls": [],
        "exc": None,
        "result": CommandResult(type="result", id="x", ok=True, data={"id": "abc123"}),
    }

    async def fake_send(node_id, action, params, timeout=90):
        state["calls"].append((action, params))
        if state["exc"] is not None:
            raise state["exc"]
        return state["result"]

    monkeypatch.setattr(broker, "send", fake_send)
    return state


@pytest.fixture
def online(client, user):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        yield node_id, headers


def _body(node_id, **changes):
    body = {
        "node_id": node_id,
        "name": "Web 1",
        "image": "nginx:1.27-alpine",
        "host_port": 25001,
        "container_port": 80,
    }
    body.update(changes)
    return body


def _post(client, headers, node_id, **changes):
    return client.post("/api/containers", json=_body(node_id, **changes), headers=headers)


def _make(client, headers, node_id):
    response = _post(client, headers, node_id)
    assert response.status_code == 201
    return response.json()["id"]


def test_create_sends_the_command_and_is_audited(client, db_session, agent, online):
    node_id, headers = online
    response = _post(client, headers, node_id)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert body["node_name"] == "node-1"
    assert body["docker_name"].startswith("ew-")

    action, params = agent["calls"][0]
    assert action == "container.create"
    assert params["name"] == body["docker_name"]
    assert params["image"] == "nginx:1.27-alpine"
    assert params["ports"] == [{"host": 25001, "container": 80, "proto": "tcp"}]
    assert params["env"] == {}

    db_session.expire_all()
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "container.create")
    ).one()
    assert entry.details["outcome"] == "ok"
    assert entry.details["host_port"] == 25001


def test_start_stop_and_delete(client, agent, online):
    node_id, headers = online
    container_id = _make(client, headers, node_id)

    started = client.post(f"/api/containers/{container_id}/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    stopped = client.post(f"/api/containers/{container_id}/stop", headers=headers)
    assert stopped.json()["status"] == "stopped"
    assert client.delete(f"/api/containers/{container_id}", headers=headers).status_code == 204
    assert client.get("/api/containers").json() == []

    actions = [call[0] for call in agent["calls"]]
    assert actions == [
        "container.create",
        "container.start",
        "container.stop",
        "container.remove",
    ]


def test_refusal_by_the_agent_frees_the_port(client, agent, online):
    node_id, headers = online
    agent["result"] = CommandResult(
        type="result", id="x", ok=False, error="image is not on the allowlist"
    )
    response = _post(client, headers, node_id)
    assert response.status_code == 422
    assert response.json()["detail"] == "image is not on the allowlist"
    assert client.get("/api/containers").json() == []

    agent["result"] = CommandResult(type="result", id="x", ok=True, data={"id": "abc123"})
    assert _post(client, headers, node_id).status_code == 201


def test_timeout_keeps_the_container_in_error_state(client, agent, online):
    node_id, headers = online
    agent["exc"] = TimeoutError()
    assert _post(client, headers, node_id).status_code == 504
    rows = client.get("/api/containers").json()
    assert rows[0]["status"] == "error"
    assert rows[0]["last_error"]


def test_port_outside_the_node_range_is_rejected(client, agent, online):
    node_id, headers = online
    assert _post(client, headers, node_id, host_port=26000).status_code == 422
    assert not agent["calls"]


def test_duplicate_port_is_rejected(client, agent, online):
    node_id, headers = online
    _make(client, headers, node_id)
    assert _post(client, headers, node_id, name="Web 2").status_code == 409
    assert len(agent["calls"]) == 1


def test_node_without_connection_gives_409(client, user, agent):
    node_id, _key = _enroll_node(client, user)
    headers = _login(client, user)
    assert _post(client, headers, node_id).status_code == 409
    assert not agent["calls"]


def test_unknown_container_gives_404(client, user, agent):
    headers = _login(client, user)
    response = client.post(f"/api/containers/{uuid.uuid4()}/start", headers=headers)
    assert response.status_code == 404


def test_delete_when_the_container_is_already_gone(client, agent, online):
    node_id, headers = online
    container_id = _make(client, headers, node_id)
    agent["result"] = CommandResult(type="result", id="x", ok=False, error=GONE)
    assert client.delete(f"/api/containers/{container_id}", headers=headers).status_code == 204
    assert client.get("/api/containers").json() == []


def test_delete_without_agent_keeps_the_entry(client, agent, online):
    node_id, headers = online
    container_id = _make(client, headers, node_id)
    agent["exc"] = AgentOffline()
    assert client.delete(f"/api/containers/{container_id}", headers=headers).status_code == 409
    rows = client.get("/api/containers").json()
    assert len(rows) == 1
    assert rows[0]["last_error"]


def test_force_delete_skips_the_agent(client, agent, online):
    node_id, headers = online
    container_id = _make(client, headers, node_id)
    agent["exc"] = AgentOffline()
    before = len(agent["calls"])
    response = client.delete(f"/api/containers/{container_id}?force=true", headers=headers)
    assert response.status_code == 204
    assert len(agent["calls"]) == before
    assert client.get("/api/containers").json() == []


def test_csrf_token_is_required(client, agent, online):
    node_id, _headers = online
    assert _post(client, {}, node_id).status_code == 403
    assert not agent["calls"]


@pytest.mark.parametrize(
    "changes",
    [
        {"image": "-rm"},
        {"image": "Nginx"},
        {"name": ""},
        {"host_port": 80},
        {"container_port": 0},
        {"protocol": "sctp"},
        {"memory_mb": 1},
        {"privileged": True},
    ],
)
def test_invalid_input_is_rejected(client, agent, online, changes):
    node_id, headers = online
    assert _post(client, headers, node_id, **changes).status_code == 422
    assert not agent["calls"]
