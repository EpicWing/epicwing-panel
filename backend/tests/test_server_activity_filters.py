import csv
import io
import re
import uuid

from app.api.audit import _csv_cell
from tests import test_server_power as base
from tests.test_server_activity import _add, _get

server = base.server
broker = base.broker

TAG = "filter-test"


def _seed(db_session, server, n, action, actor=None, **extra):
    values = {"actor_id": actor} if actor else {}
    return _add(
        db_session, server, n, action=action, details={"n": n, "tag": TAG, **extra}, **values
    )


def _ns(response):
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    return sorted(i["details"]["n"] for i in items if (i["details"] or {}).get("tag") == TAG)


def _export(client, server, **params):
    return client.get(server.url + "/activity/export", params=params, headers=server.headers)


def test_group_filter(client, db_session, server):
    _seed(db_session, server, 1, "server.power")
    _seed(db_session, server, 2, "server.file.write")
    _seed(db_session, server, 3, "server.backup.create")
    assert _ns(_get(client, server)) == [1, 2, 3]
    assert _ns(_get(client, server, groups=["power"])) == [1]
    assert _ns(_get(client, server, groups=["power", "backups"])) == [1, 3]


def test_unknown_group_gives_422(client, server):
    assert _get(client, server, groups=["nonsense"]).status_code == 422


def test_date_range(client, db_session, server):
    _seed(db_session, server, 1, "server.power")
    _seed(db_session, server, 2, "server.power")
    assert _ns(_get(client, server, since="2026-01-01", until="2026-01-01")) == [1, 2]
    assert _ns(_get(client, server, since="2026-01-02")) == []
    assert _ns(_get(client, server, until="2025-12-31")) == []


def test_reversed_range_gives_422(client, server):
    assert _get(client, server, since="2026-02-01", until="2026-01-01").status_code == 422


def test_search_matches_details_and_ignores_case(client, db_session, server):
    _seed(db_session, server, 1, "server.file.write", path="plugins/Alpha.dll")
    _seed(db_session, server, 2, "server.file.write", path="config/beta")
    assert _ns(_get(client, server, q="alpha")) == [1]
    assert _ns(_get(client, server, q="BETA")) == [2]


def test_search_treats_wildcards_literally(client, db_session, server):
    _seed(db_session, server, 1, "server.file.write", path="plugins/alpha.dll")
    assert _ns(_get(client, server, q="%")) == []
    assert _ns(_get(client, server, q="_")) == []


def test_search_matches_the_name_part_of_the_user(client, db_session, server, user):
    _seed(db_session, server, 1, "server.power", actor=uuid.UUID(str(user.id)))
    _seed(db_session, server, 2, "server.power")
    assert _ns(_get(client, server, q=user.email.split("@")[0])) == [1]


def test_search_is_limited_in_length(client, server):
    assert _get(client, server, q="x" * 101).status_code == 422


def test_csv_export(client, db_session, server):
    _seed(db_session, server, 1, "server.file.write", path="plugins/a.dll")
    response = _export(client, server, format="csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert re.fullmatch(
        r'attachment; filename="activity-[0-9a-f]{8}\.csv"',
        response.headers["content-disposition"],
    )
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["time", "user", "action", "ip", "details"]
    assert any(TAG in row[4] for row in rows[1:])


def test_json_export_follows_the_filters(client, db_session, server):
    _seed(db_session, server, 1, "server.power")
    _seed(db_session, server, 2, "server.file.write")
    response = _export(client, server, format="json", groups=["files"])
    assert response.status_code == 200, response.text
    items = response.json()
    assert items
    assert all(i["action"].startswith("server.file.") for i in items)
    assert [i["details"]["n"] for i in items if (i["details"] or {}).get("tag") == TAG] == [2]


def test_export_rejects_unknown_formats(client, server):
    assert _export(client, server, format="xml").status_code == 422


def test_csv_cells_cannot_start_a_formula():
    for value in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
        assert _csv_cell(value) == "'" + value
    assert _csv_cell("plain") == "plain"
    assert _csv_cell("") == ""
