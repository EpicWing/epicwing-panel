from datetime import UTC, datetime

import pytest

from app.models import SshKey, User
from app.models.server import ServerMember, ServerMemberPermission
from app.services import sftp as sftp_service
from tests.test_admin_overview import _egg, _node, _server
from tests.test_agent_ws import WS_URL, _enroll_node, _login_agent, _server_on


@pytest.fixture
def headers(client, credentials):
    reply = client.post("/api/auth/login", json=credentials)
    assert reply.status_code == 200, reply.text
    return {"X-CSRF-Token": reply.json()["csrf_token"]}


@pytest.fixture
def world(client, user, headers, db_session):
    node_id = _node(client, headers, "node-a")
    server = _server(db_session, user, node_id, _egg(client, headers))
    return node_id, server


def _key(db, account, fingerprint):
    row = SshKey(
        user_id=account.id,
        name="k",
        key_type="ssh-ed25519",
        public_key="x",
        fingerprint=fingerprint,
    )
    db.add(row)
    db.commit()
    return row


def _plain_user(db, email="member@example.test"):
    account = User(email=email, password_hash="not-a-real-hash")
    db.add(account)
    db.commit()
    return account


def _member(db, server, account, *permissions):
    member = ServerMember(server_id=server.id, user_id=account.id)
    db.add(member)
    db.flush()
    for permission in permissions:
        db.add(ServerMemberPermission(member_id=member.id, permission=permission))
    db.commit()


def test_owner_gets_read_and_write(db_session, user, world):
    node_id, server = world
    key = _key(db_session, user, "SHA256:owner")
    grant = sftp_service.authorize(db_session, node_id, "SHA256:owner", str(server.id)[:8])
    assert grant is not None
    assert grant.server_id == server.id
    assert grant.write is True
    assert key.last_used_at is not None


def test_unknown_fingerprint_is_rejected(db_session, world):
    node_id, server = world
    assert sftp_service.authorize(db_session, node_id, "SHA256:nope", str(server.id)[:8]) is None


def test_server_of_another_node_is_rejected(client, headers, db_session, user, world):
    _, server = world
    other_node = _node(client, headers, "node-b")
    _key(db_session, user, "SHA256:owner")
    assert (
        sftp_service.authorize(db_session, other_node, "SHA256:owner", str(server.id)[:8])
        is None
    )


@pytest.mark.parametrize("ref", ["", "abc", "zzzzzzzz", "../../etc", "a" * 40])
def test_bad_references_are_rejected(db_session, user, world, ref):
    node_id, _ = world
    _key(db_session, user, "SHA256:owner")
    assert sftp_service.authorize(db_session, node_id, "SHA256:owner", ref) is None


def test_disabled_user_is_rejected(db_session, user, world):
    node_id, server = world
    _key(db_session, user, "SHA256:owner")
    user.disabled_at = datetime.now(UTC)
    db_session.commit()
    assert sftp_service.authorize(db_session, node_id, "SHA256:owner", str(server.id)[:8]) is None


def test_member_with_read_only_gets_no_write(db_session, world):
    node_id, server = world
    member = _plain_user(db_session)
    _key(db_session, member, "SHA256:member")
    _member(db_session, server, member, "files.read")
    grant = sftp_service.authorize(db_session, node_id, "SHA256:member", str(server.id)[:8])
    assert grant is not None and grant.write is False


def test_member_with_read_and_write(db_session, world):
    node_id, server = world
    member = _plain_user(db_session)
    _key(db_session, member, "SHA256:member")
    _member(db_session, server, member, "files.read", "files.write")
    grant = sftp_service.authorize(db_session, node_id, "SHA256:member", str(server.id)[:8])
    assert grant is not None and grant.write is True


def test_member_without_file_rights_is_rejected(db_session, world):
    node_id, server = world
    member = _plain_user(db_session)
    _key(db_session, member, "SHA256:member")
    _member(db_session, server, member, "console.view")
    assert sftp_service.authorize(db_session, node_id, "SHA256:member", str(server.id)[:8]) is None


def test_stranger_is_rejected(db_session, world):
    node_id, server = world
    stranger = _plain_user(db_session, "stranger@example.test")
    _key(db_session, stranger, "SHA256:stranger")
    assert (
        sftp_service.authorize(db_session, node_id, "SHA256:stranger", str(server.id)[:8]) is None
    )


def _read_result(ws):
    for _ in range(5):
        frame = ws.receive_json()
        if frame.get("type") == "sftp_auth_result":
            return frame
    raise AssertionError("keine sftp_auth_result-Antwort")


def test_agent_frame_roundtrip(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    server_id = _server_on(client, user, node_id, 25001)
    _key(db_session, user, "SHA256:owner")
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        ws.send_json(
            {"type": "sftp_auth", "id": "a1", "fingerprint": "SHA256:owner", "server": server_id[:8]}
        )
        assert _read_result(ws) == {
            "type": "sftp_auth_result",
            "id": "a1",
            "ok": True,
            "server": server_id,
            "write": True,
        }
        ws.send_json(
            {"type": "sftp_auth", "id": "a2", "fingerprint": "SHA256:nope", "server": server_id[:8]}
        )
        assert _read_result(ws) == {"type": "sftp_auth_result", "id": "a2", "ok": False}
