"""Fehler beim Start und der Installation: Nutzer sehen nie den Rohtext des Agents."""

import importlib

import pytest
from sqlalchemy import select

from app.agentlink.commands import AgentOffline
from app.agentlink.protocol import CommandResult
from app.models import AuditLog
from app.services import server_state
from app.services.agent_errors import GENERIC_MESSAGE, MESSAGES
from tests import test_server_access as _access
from tests.test_nodes_detail import _login
from tests.test_server_members import _as

world = _access.world

RAW = (
    "docker start: exit status 1: Error response from daemon: failed to set up container "
    "networking: Bind for 203.0.113.154:27015 failed: port is already allocated"
)


class CodedBroker:
    """Wie FakeBroker, aber der Fehler kann einen Code mitbringen."""

    def __init__(self):
        self.calls = []
        self.failures = {}
        self.offline = False

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append(action)
        if self.offline:
            raise AgentOffline
        failure = self.failures.get(action)
        if failure is None:
            return CommandResult(type="result", id="x", ok=True, data={})
        code, text = failure
        return CommandResult(type="result", id="x", ok=False, error=text, code=code, data={})


@pytest.fixture
def broker(monkeypatch):
    fake = CodedBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


@pytest.fixture
def installed(client, user, world, broker):
    admin_headers = _login(client, user)
    assert client.post(world.url + "/install", headers=admin_headers).status_code == 200
    broker.calls.clear()
    return world


def _start(client, world, headers):
    return client.post(world.url + "/power", json={"action": "start"}, headers=headers)


def _audit(db_session, action):
    db_session.expire_all()
    return list(db_session.scalars(select(AuditLog).where(AuditLog.action == action)))


def test_user_sees_a_friendly_message_and_no_raw_text(client, db_session, installed, broker):
    broker.failures["container.start"] = ("PORT_IN_USE", RAW)
    owner = _as(client, installed.owner)
    response = _start(client, installed, owner)
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "PORT_IN_USE"
    assert body["detail"] == MESSAGES["PORT_IN_USE"]
    assert "technical" not in body
    assert "203.0.113.154" not in response.text and "docker" not in response.text.lower()


def test_last_error_is_the_friendly_text(client, installed, broker):
    broker.failures["container.start"] = ("PORT_IN_USE", RAW)
    owner = _as(client, installed.owner)
    _start(client, installed, owner)
    shown = client.get(installed.url).json()
    assert shown["status"] == "error"
    assert shown["last_error"] == MESSAGES["PORT_IN_USE"]
    assert "203.0.113.154" not in str(shown)


def test_admin_gets_the_technical_text_too(client, user, installed, broker):
    broker.failures["container.start"] = ("PORT_IN_USE", RAW)
    admin = _login(client, user)
    body = _start(client, installed, admin).json()
    assert body["detail"] == MESSAGES["PORT_IN_USE"]
    assert body["technical"] == RAW


def test_raw_text_goes_to_the_audit_log(client, db_session, installed, broker):
    broker.failures["container.start"] = ("PORT_IN_USE", RAW)
    owner = _as(client, installed.owner)
    _start(client, installed, owner)
    [entry] = _audit(db_session, "server.power_failed")
    assert entry.details["code"] == "PORT_IN_USE"
    assert entry.details["technical"] == RAW
    assert entry.details["action"] == "start"


def test_unknown_code_and_old_agents_get_the_generic_message(client, installed, broker):
    owner = _as(client, installed.owner)
    for code in ("SOMETHING_NEW", None):
        broker.failures["container.start"] = (code, "internal detail 12345")
        body = _start(client, installed, owner).json()
        assert body["detail"] == GENERIC_MESSAGE
        assert "12345" not in str(body)


def test_start_is_refused_for_a_server_that_is_not_installed(client, world, broker):
    owner = _as(client, world.owner)
    response = _start(client, world, owner)
    assert response.status_code == 409
    assert response.json()["detail"] == "This server has not been installed yet. Install it first."
    assert broker.calls == []


def test_install_never_starts_the_container(client, user, world, broker):
    admin = _login(client, user)
    assert client.post(world.url + "/install", headers=admin).status_code == 200
    assert broker.calls == ["container.create"]


def test_install_failure_is_friendly_and_audited(client, user, db_session, world, broker):
    broker.failures["container.create"] = ("SOMETHING_NEW", "image not allowed: secret-registry/x")
    owner = _as(client, world.owner)
    response = client.post(world.url + "/install", headers=owner)
    assert response.status_code == 502
    assert response.json()["detail"] == GENERIC_MESSAGE
    assert "secret-registry" not in response.text
    [entry] = _audit(db_session, "server.install_failed")
    assert entry.details["technical"] == "image not allowed: secret-registry/x"
    admin = _login(client, user)
    body = client.post(world.url + "/install", headers=admin).json()
    assert body["technical"] == "image not allowed: secret-registry/x"


def test_busy_and_missing_container_have_their_own_messages(client, installed, broker):
    owner = _as(client, installed.owner)
    for code in ("BACKUP_RUNNING", "NODE_BUSY", "CONTAINER_MISSING"):
        broker.failures["container.start"] = (code, "x")
        assert _start(client, installed, owner).json()["detail"] == MESSAGES[code]
        # A new start is allowed from "error".


def test_offline_node_message_is_unchanged(client, installed, broker):
    broker.offline = True
    owner = _as(client, installed.owner)
    response = _start(client, installed, owner)
    assert response.status_code == 409
    assert response.json()["detail"] == "The node is offline."


@pytest.mark.parametrize("code", [126, 127])
def test_exit_126_and_127_explain_missing_files(code):
    new_status, error = server_state.next_status("starting", "exited", code)
    assert new_status == "error"
    assert "reinstalling" in error and str(code) not in error


def test_other_exit_codes_keep_their_message():
    assert server_state.next_status("running", "exited", 137) == (
        "error",
        "The container exited with code 137.",
    )
    assert server_state.next_status("starting", "exited", 0) == ("offline", None)
