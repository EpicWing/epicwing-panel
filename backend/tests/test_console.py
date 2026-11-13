import asyncio
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.agentlink.commands import AgentOffline, broker
from app.agentlink.console import ConsoleHub, TicketStore
from app.agentlink.protocol import CommandResult
from app.main import app
from app.models import Server
from app.services.server_state import next_status
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_agent_ws import WS_URL, _enroll_node, _login_agent
from tests.test_nodes_detail import _login


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.offline = False
        self.error = None

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((action, params))
        if self.offline:
            raise AgentOffline
        return CommandResult(
            type="result", id="x", ok=self.error is None, error=self.error, data={}
        )

    def count(self, action):
        return sum(1 for a, _ in self.calls if a == action)


@pytest.fixture
def fake(monkeypatch):
    fake = FakeBroker()
    monkeypatch.setattr(broker, "send", fake.send)
    return fake


@pytest.fixture
def setup(client, user, fake):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run")
    allocations = make_allocations(client, headers, node_id, 25001, 25001)
    body = {
        "name": "Game 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
    }
    created = client.post("/api/servers", json=body, headers=headers).json()
    return SimpleNamespace(server_id=created["id"], node_id=node_id, key=key, headers=headers)


def _ticket(client, ctx):
    response = client.post(f"/api/servers/{ctx.server_id}/console/ticket", headers=ctx.headers)
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


def _url(ctx, ticket):
    return f"/api/servers/{ctx.server_id}/console?ticket={ticket}"


def _eventually(check, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


def test_ticket_needs_login():
    assert TestClient(app).post(f"/api/servers/{uuid.uuid4()}/console/ticket").status_code == 401


def test_ticket_for_unknown_server_is_404(client, user):
    headers = _login(client, user)
    response = client.post(f"/api/servers/{uuid.uuid4()}/console/ticket", headers=headers)
    assert response.status_code == 404


def test_connect_without_a_ticket_is_refused(client, setup):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_url(setup, "")):
        pass


def test_ticket_is_single_use(client, setup):
    ticket = _ticket(client, setup)
    with client.websocket_connect(_url(setup, ticket)) as browser:
        assert browser.receive_json()["type"] == "status"
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_url(setup, ticket)):
        pass


def test_output_and_status_reach_the_browser(client, db_session, setup):
    sid = setup.server_id
    server = db_session.get(Server, uuid.UUID(sid))
    server.status = "starting"
    db_session.commit()
    with client.websocket_connect(WS_URL) as agent:
        _login_agent(agent, setup.node_id, setup.key)
        with client.websocket_connect(_url(setup, _ticket(client, setup))) as browser:
            assert browser.receive_json() == {"type": "status", "status": "starting"}
            agent.send_json({"type": "console", "name": sid, "data": "hello\r\n"})
            assert browser.receive_json() == {"type": "output", "data": "hello\r\n"}
            agent.send_json({"type": "state", "name": sid, "state": "running"})
            assert browser.receive_json() == {"type": "status", "status": "running"}
    db_session.expire_all()
    assert db_session.get(Server, uuid.UUID(sid)).status == "running"


def test_input_is_forwarded(client, setup, fake):
    with client.websocket_connect(_url(setup, _ticket(client, setup))) as browser:
        browser.receive_json()
        browser.send_json({"type": "input", "data": "say hi"})
        browser.send_json({"type": "nope"})
        assert browser.receive_json()["type"] == "error"
    assert ("console.input", {"name": setup.server_id, "data": "say hi"}) in fake.calls


def test_control_characters_are_not_forwarded(client, setup, fake):
    with client.websocket_connect(_url(setup, _ticket(client, setup))) as browser:
        browser.receive_json()
        browser.send_json({"type": "input", "data": "a\nb"})
        assert browser.receive_json()["type"] == "error"
    assert fake.count("console.input") == 0


def test_offline_node_gives_an_error_message(client, setup, fake):
    fake.offline = True
    with client.websocket_connect(_url(setup, _ticket(client, setup))) as browser:
        # The known status arrives first, then the error from the agent.
        assert browser.receive_json()["type"] == "status"
        message = browser.receive_json()
    assert message["type"] == "error"
    assert "offline" in message["message"]


def test_watch_and_unwatch_follow_the_viewers(client, setup, fake):
    with client.websocket_connect(_url(setup, _ticket(client, setup))) as first:
        first.receive_json()
        with client.websocket_connect(_url(setup, _ticket(client, setup))) as second:
            second.receive_json()
        assert fake.count("console.unwatch") == 0
    assert _eventually(lambda: fake.count("console.unwatch") == 1)
    assert fake.count("console.watch") == 1


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


class FakeCommands:
    def __init__(self):
        self.calls = []

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((node_id, action))
        return CommandResult(type="result", id="x", ok=True, data={})


def test_hub_ignores_frames_from_another_node():
    async def scenario():
        hub = ConsoleHub(FakeCommands())
        socket = FakeSocket()
        node, other = uuid.uuid4(), uuid.uuid4()
        await hub.subscribe("s1", node, socket)
        await hub.publish(other, "s1", {"x": 1})
        assert socket.sent == []
        await hub.publish(node, "s1", {"x": 1})
        assert socket.sent == [{"x": 1}]

    asyncio.run(scenario())


def test_hub_rewatches_only_the_given_node():
    async def scenario():
        commands = FakeCommands()
        hub = ConsoleHub(commands)
        node, other = uuid.uuid4(), uuid.uuid4()
        await hub.subscribe("s1", node, FakeSocket())
        await hub.subscribe("s2", other, FakeSocket())
        commands.calls.clear()
        await hub.rewatch(node)
        assert commands.calls == [(node, "console.watch")]

    asyncio.run(scenario())


def test_tickets_are_bound_to_the_server_and_single_use():
    store = TicketStore()
    user, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = store.issue(user, first)
    assert store.redeem(token, second) is None
    assert store.redeem(token, first) is None
    token = store.issue(user, first)
    assert store.redeem(token, first) == user
    assert store.redeem(token, first) is None


@pytest.mark.parametrize(
    ("status", "state", "code", "expected"),
    [
        ("offline", "running", None, ("running", None)),
        ("starting", "running", None, ("running", None)),
        ("error", "running", None, ("running", None)),
        ("new", "running", None, (None, None)),
        ("installing", "running", None, (None, None)),
        ("running", "exited", 0, ("offline", None)),
        ("running", "exited", 137, ("error", "The container exited with code 137.")),
        ("starting", "exited", 1, ("error", "The container exited with code 1.")),
        ("stopping", "exited", 143, ("offline", None)),
        ("offline", "exited", 1, (None, None)),
        ("running", "removed", None, ("error", "The container was removed.")),
        ("installing", "removed", None, (None, None)),
        ("offline", "removed", None, (None, None)),
        ("running", "created", None, ("offline", None)),
        ("offline", "created", None, (None, None)),
    ],
)
def test_next_status(status, state, code, expected):
    assert next_status(status, state, code) == expected
