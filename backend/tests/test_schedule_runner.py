import asyncio
import importlib
import uuid

import pytest
from fastapi import HTTPException

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


def _prepare(db_session, server, status="running", only_when_online=True, tasks=()):
    row = db_session.get(Server, uuid.UUID(server.id))
    row.status = status
    schedule = Schedule(server_id=row.id, name="t", only_when_online=only_when_online)
    db_session.add(schedule)
    db_session.commit()
    for number, (action, payload, offset, keep_going) in enumerate(tasks, start=1):
        db_session.add(
            ScheduleTask(
                schedule_id=schedule.id,
                sequence=number,
                action=action,
                payload=payload,
                time_offset=offset,
                continue_on_failure=keep_going,
            )
        )
    db_session.commit()
    return schedule.id


def _run(db_session, schedule_id, **kwargs):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    result = asyncio.run(
        schedule_runner.run_schedule(db_session, schedule_id, sleep=fake_sleep, **kwargs)
    )
    return result, slept


@pytest.fixture
def calls(monkeypatch):
    log = []

    async def power(db, srv, action):
        log.append(("power", action))

    async def backup(db, srv, name, ignored, is_locked, created_by):
        log.append(("backup", ignored))

    async def send_input(node_id, name, data):
        log.append(("command", data))

    monkeypatch.setattr(schedule_runner, "perform_power", power)
    monkeypatch.setattr(schedule_runner, "perform_backup", backup)
    monkeypatch.setattr(schedule_runner.hub, "send_input", send_input)
    return log


def test_tasks_run_in_order_with_offsets(db_session, server, calls):
    sid = _prepare(
        db_session,
        server,
        tasks=[
            ("power", "stop", 0, False),
            ("command", "say hi", 5, False),
            ("backup", "*.log", 0, False),
            ("power", "start", 30, False),
        ],
    )
    result, slept = _run(db_session, sid)
    assert result.state == "ok"
    assert calls == [
        ("power", "stop"),
        ("command", "say hi\n"),
        ("backup", "*.log"),
        ("power", "start"),
    ]
    assert slept == [5, 30]
    db_session.expire_all()
    assert db_session.get(Schedule, sid).last_run_at is not None


def test_a_failure_stops_the_schedule(db_session, server, calls, monkeypatch):
    async def boom(db, srv, action):
        raise HTTPException(409, "nope")

    monkeypatch.setattr(schedule_runner, "perform_power", boom)
    sid = _prepare(
        db_session, server, tasks=[("power", "restart", 0, False), ("command", "x", 0, False)]
    )
    result, _ = _run(db_session, sid)
    assert result.state == "failed" and "nope" in result.detail
    assert calls == []


def test_continue_on_failure_keeps_going(db_session, server, calls, monkeypatch):
    async def boom(db, srv, action):
        raise HTTPException(409, "nope")

    monkeypatch.setattr(schedule_runner, "perform_power", boom)
    sid = _prepare(
        db_session, server, tasks=[("power", "restart", 0, True), ("command", "x", 0, False)]
    )
    result, _ = _run(db_session, sid)
    assert result.state == "failed" and "nope" in result.detail
    assert calls == [("command", "x\n")]


def test_scheduled_run_skips_an_offline_server(db_session, server, calls):
    sid = _prepare(db_session, server, status="offline", tasks=[("power", "start", 0, False)])
    result, _ = _run(db_session, sid, trigger="schedule")
    assert result.state == "skipped"
    assert calls == []
    db_session.expire_all()
    assert db_session.get(Schedule, sid).last_run_at is None


def test_manual_run_ignores_only_when_online(db_session, server, calls):
    sid = _prepare(db_session, server, status="offline", tasks=[("power", "start", 0, False)])
    result, _ = _run(db_session, sid)
    assert result.state == "ok"
    assert calls == [("power", "start")]


def test_command_needs_a_running_server(db_session, server, calls):
    sid = _prepare(
        db_session,
        server,
        status="offline",
        only_when_online=False,
        tasks=[("command", "say hi", 0, False)],
    )
    result, _ = _run(db_session, sid)
    assert result.state == "failed" and "not running" in result.detail
    assert calls == []


def test_a_running_schedule_is_not_started_twice(db_session, server, calls, monkeypatch):
    sid = _prepare(db_session, server, tasks=[("power", "stop", 0, False)])
    monkeypatch.setattr(schedule_runner, "_running", {sid})
    result, _ = _run(db_session, sid)
    assert result.state == "busy"
    assert calls == []


def test_the_lock_is_released_after_a_run(db_session, server, calls):
    sid = _prepare(db_session, server, tasks=[("power", "stop", 0, False)])
    _run(db_session, sid)
    assert not schedule_runner.is_running(sid)
