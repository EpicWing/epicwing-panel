import asyncio
import importlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Schedule
from app.services import schedule_runner, scheduler
from tests import test_server_power as base
from tests.test_server_files import FileBroker

server = base.server

NOW = datetime(2026, 10, 18, 4, 0, 30, tzinfo=UTC)


@pytest.fixture
def broker(monkeypatch):
    fake = FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def _add(db_session, server, **values):
    row = Schedule(
        server_id=uuid.UUID(server.id),
        name="t",
        cron_minute="0",
        cron_hour="4",
        next_run_at=values.pop("next_run_at", NOW - timedelta(seconds=30)),
        **values,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_due_schedule_is_launched_and_moved_forward(db_session, server):
    row = _add(db_session, server)
    launched = []
    assert scheduler.tick(db_session, NOW, launched.append) == [row.id]
    assert launched == [row.id]
    db_session.expire_all()
    moved = db_session.get(Schedule, row.id).next_run_at.replace(tzinfo=UTC)
    assert moved == datetime(2026, 10, 19, 4, 0, tzinfo=UTC)


def test_second_tick_does_not_launch_again(db_session, server):
    _add(db_session, server)
    launched = []
    scheduler.tick(db_session, NOW, launched.append)
    scheduler.tick(db_session, NOW + timedelta(seconds=30), launched.append)
    assert len(launched) == 1


def test_future_and_disabled_schedules_are_left_alone(db_session, server):
    _add(db_session, server, next_run_at=NOW + timedelta(hours=1))
    _add(db_session, server, enabled=False)
    launched = []
    assert scheduler.tick(db_session, NOW, launched.append) == []
    assert launched == []


def test_missed_run_is_skipped_but_rescheduled(db_session, server):
    row = _add(db_session, server, next_run_at=NOW - timedelta(hours=2))
    launched = []
    assert scheduler.tick(db_session, NOW, launched.append) == []
    assert launched == []
    db_session.expire_all()
    assert db_session.get(Schedule, row.id).next_run_at.replace(tzinfo=UTC) > NOW


def test_invalid_cron_is_switched_off(db_session, server):
    row = _add(db_session, server)
    row.cron_minute = "99"
    db_session.commit()
    launched = []
    assert scheduler.tick(db_session, NOW, launched.append) == []
    db_session.expire_all()
    assert db_session.get(Schedule, row.id).next_run_at is None


def test_background_run_uses_the_schedule_trigger(monkeypatch):
    seen = []

    async def fake_run(db, schedule_id, trigger="manual", **kwargs):
        seen.append(trigger)

    class Dummy:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(schedule_runner, "run_schedule", fake_run)
    monkeypatch.setattr(schedule_runner, "open_session", lambda: Dummy())
    captured = []
    monkeypatch.setattr(schedule_runner, "spawn", captured.append)
    schedule_runner.run_in_background(uuid.uuid4(), "schedule")
    asyncio.run(captured[0])
    assert seen == ["schedule"]
