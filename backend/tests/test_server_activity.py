import uuid
from datetime import UTC, datetime

from app.api.audit import _item
from app.models import AuditLog
from tests import test_server_power as base

server = base.server
broker = base.broker

MARK = "server.test.event"


def _add(db_session, server, n, **values):
    row = AuditLog(
        action=values.pop("action", MARK),
        target_type=values.pop("target_type", "server"),
        target_id=values.pop("target_id", server.id),
        details=values.pop("details", {"n": n}),
        created_at=datetime(2026, 1, 1, 12, 0, n, tzinfo=UTC),
        **values,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _get(client, server, **params):
    return client.get(server.url + "/activity", params=params, headers=server.headers)


def _marked(response):
    return [item for item in response.json()["items"] if item["action"] == MARK]


def test_entries_of_this_server_come_newest_first(client, db_session, server):
    for n in range(3):
        _add(db_session, server, n)
    response = _get(client, server)
    assert response.status_code == 200, response.text
    assert [item["details"]["n"] for item in _marked(response)] == [2, 1, 0]


def test_other_servers_and_other_targets_are_not_listed(client, db_session, server):
    _add(db_session, server, 1)
    _add(db_session, server, 2, target_id=str(uuid.uuid4()))
    _add(db_session, server, 3, target_type="node")
    marked = _marked(_get(client, server))
    assert [item["details"]["n"] for item in marked] == [1]


def test_pagination_has_no_overlap_and_reports_more(client, db_session, server):
    for n in range(5):
        _add(db_session, server, n)
    everything = _get(client, server, limit=100).json()
    total = len(everything["items"])
    assert total >= 5
    assert everything["has_more"] is False
    first = _get(client, server, limit=2).json()
    second = _get(client, server, limit=2, offset=2).json()
    assert len(first["items"]) == 2
    assert first["has_more"] is True
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    last = _get(client, server, limit=2, offset=total - 1).json()
    assert len(last["items"]) == 1
    assert last["has_more"] is False
    assert _get(client, server, limit=2, offset=total).json() == {"items": [], "has_more": False}


def test_owner_sees_actor_email_and_ip(client, db_session, server, user):
    _add(db_session, server, 1, actor_id=uuid.UUID(str(user.id)), ip="203.0.113.7")
    item = _marked(_get(client, server))[0]
    assert "@" in item["actor"]
    assert item["ip"] == "203.0.113.7"


def test_entry_of_a_deleted_user_has_no_actor(client, db_session, server):
    _add(db_session, server, 1)
    assert _marked(_get(client, server))[0]["actor"] is None


def test_item_hides_the_ip_unless_allowed():
    row = AuditLog(
        id=uuid.uuid4(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        action=MARK,
        ip="203.0.113.7",
        details=None,
    )
    assert _item(row, "a@example.com", show_ip=True).ip == "203.0.113.7"
    assert _item(row, "a@example.com", show_ip=False).ip is None
    assert _item(row, None, show_ip=False).actor is None


def test_unknown_server_gives_404(client, server):
    response = client.get(f"/api/servers/{uuid.uuid4()}/activity", headers=server.headers)
    assert response.status_code == 404


def test_limit_must_be_positive(client, server):
    assert _get(client, server, limit=0).status_code == 422


def test_console_opens_are_not_listed(client, db_session, server):
    _add(db_session, server, 1, action="server.console_open")
    _add(db_session, server, 2)
    actions = [item["action"] for item in _get(client, server, limit=100).json()["items"]]
    assert "server.console_open" not in actions
    assert MARK in actions
