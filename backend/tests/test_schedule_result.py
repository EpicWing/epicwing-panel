import asyncio
import importlib
import uuid

import pytest

from app.models import Schedule, ScheduleTask, Server
from app.services import schedule_runner
from tests import test_server_power as base
from tests.test_server_files import FileBroker

server = base.server


@pytest.fixture
def broker(monkeypatch):
    fake = FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def _schedule(db_session, server, status):
    row = db_session.get(Server, uuid.UUID(server.id))
    row.status = status
    db_session.commit()
    schedule = Schedule(server_id=row.id, name="t", cron_minute="0", cron_hour="4")
    db_session.add(schedule)
    db_session.commit()
    db_session.add(
        ScheduleTask(schedule_id=schedule.id, sequence=1, action="power", payload="restart")
    )
    db_session.commit()
    return schedule


def test_skipped_run_is_stored(db_session, server):
    schedule = _schedule(db_session, server, "offline")
    result = asyncio.run(schedule_runner.run_schedule(db_session, schedule.id, trigger="schedule"))
    assert result.state == "skipped"
    db_session.expire_all()
    stored = db_session.get(Schedule, schedule.id)
    assert stored.last_result == "skipped"
    assert "offline" in stored.last_detail


def test_failed_run_is_stored(db_session, server):
    schedule = _schedule(db_session, server, "offline")
    result = asyncio.run(schedule_runner.run_schedule(db_session, schedule.id))
    assert result.state == "failed"
    db_session.expire_all()
    stored = db_session.get(Schedule, schedule.id)
    assert stored.last_result == "failed"
    assert "offline" in stored.last_detail


def test_api_reports_last_result(client, server):
    response = client.post(
        server.url + "/schedules",
        json={"name": "Daily restart", "minute": "0", "hour": "4"},
        headers=server.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["last_result"] is None
    assert body["last_detail"] is None
