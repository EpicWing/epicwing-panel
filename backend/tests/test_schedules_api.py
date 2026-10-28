import importlib
import uuid

import pytest

from app.models import Schedule
from app.services import schedule_runner
from tests import test_server_power as base
from tests.test_server_files import FileBroker

server = base.server


@pytest.fixture
def broker(monkeypatch):
    fake = FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def _url(server):
    return server.url + "/schedules"


def _create(client, server, **body):
    payload = {"name": "Daily restart", "minute": "0", "hour": "4"}
    payload.update(body)
    return client.post(_url(server), json=payload, headers=server.headers)


def _task(client, server, schedule_id, **body):
    payload = {"action": "power", "payload": "restart"}
    payload.update(body)
    return client.post(
        f"{_url(server)}/{schedule_id}/tasks", json=payload, headers=server.headers
    )


def test_create_and_list(client, server):
    response = _create(client, server)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Daily restart"
    assert (body["minute"], body["hour"]) == ("0", "4")
    assert body["next_run_at"] is not None
    assert body["tasks"] == []
    listed = client.get(_url(server), headers=server.headers).json()
    assert [row["id"] for row in listed] == [body["id"]]


def test_invalid_cron_is_rejected(client, server):
    assert _create(client, server, minute="60").status_code == 422
    assert _create(client, server, hour="*;ls").status_code == 422
    assert _create(client, server, name="   ").status_code == 422


def test_disabled_schedule_has_no_next_run(client, server):
    body = _create(client, server, enabled=False).json()
    assert body["next_run_at"] is None


def test_update_recomputes_the_next_run(client, server):
    sid = _create(client, server, enabled=False).json()["id"]
    response = client.patch(
        f"{_url(server)}/{sid}", json={"enabled": True, "hour": "5"}, headers=server.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["hour"] == "5"
    assert response.json()["next_run_at"] is not None
    bad = client.patch(f"{_url(server)}/{sid}", json={"minute": "99"}, headers=server.headers)
    assert bad.status_code == 422


def test_tasks_get_increasing_sequence(client, server):
    sid = _create(client, server).json()["id"]
    assert _task(client, server, sid).status_code == 201
    body = _task(client, server, sid, action="command", payload="say hi", time_offset=10).json()
    assert [(t["sequence"], t["action"]) for t in body["tasks"]] == [(1, "power"), (2, "command")]
    assert body["tasks"][1]["time_offset"] == 10


def test_invalid_tasks_are_rejected(client, server):
    sid = _create(client, server).json()["id"]
    assert _task(client, server, sid, payload="explode").status_code == 422
    assert _task(client, server, sid, action="command", payload="a\nb").status_code == 422
    assert _task(client, server, sid, action="command", payload="  ").status_code == 422
    assert _task(client, server, sid, time_offset=901).status_code == 422
    assert _task(client, server, sid, action="shell", payload="ls").status_code == 422


def test_task_limit(client, server):
    sid = _create(client, server).json()["id"]
    for _ in range(10):
        assert _task(client, server, sid).status_code == 201
    assert _task(client, server, sid).status_code == 409


def test_delete_task_and_schedule(client, server):
    sid = _create(client, server).json()["id"]
    body = _task(client, server, sid).json()
    task_id = body["tasks"][0]["id"]
    response = client.delete(f"{_url(server)}/{sid}/tasks/{task_id}", headers=server.headers)
    assert response.status_code == 200 and response.json()["tasks"] == []
    assert client.delete(f"{_url(server)}/{sid}", headers=server.headers).status_code == 204
    assert client.get(f"{_url(server)}/{sid}", headers=server.headers).status_code == 404


def test_unknown_schedule_is_404(client, server):
    missing = uuid.uuid4()
    assert client.get(f"{_url(server)}/{missing}", headers=server.headers).status_code == 404


def test_execute_starts_a_background_run(client, server, monkeypatch):
    started = []
    monkeypatch.setattr(schedule_runner, "run_in_background", started.append)
    sid = _create(client, server).json()["id"]
    empty = client.post(f"{_url(server)}/{sid}/execute", headers=server.headers)
    assert empty.status_code == 409
    _task(client, server, sid)
    response = client.post(f"{_url(server)}/{sid}/execute", headers=server.headers)
    assert response.status_code == 202, response.text
    assert started == [uuid.UUID(sid)]


def test_execute_refuses_a_running_schedule(client, server, monkeypatch):
    sid = _create(client, server).json()["id"]
    _task(client, server, sid)
    monkeypatch.setattr(schedule_runner, "_running", {uuid.UUID(sid)})
    response = client.post(f"{_url(server)}/{sid}/execute", headers=server.headers)
    assert response.status_code == 409


def test_schedule_limit(client, server, db_session):
    for number in range(20):
        db_session.add(Schedule(server_id=uuid.UUID(server.id), name=f"s{number}"))
    db_session.commit()
    assert _create(client, server).status_code == 409
