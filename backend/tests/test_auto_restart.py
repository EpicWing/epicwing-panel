import asyncio
import importlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.agentlink.console import hub
from app.agentlink.protocol import CommandResult, StateFrame
from app.models import Server
from app.services import auto_restart, lifecycle
from app.services.server_state import apply_state
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login


class _Broker:
    async def send(self, node_id, action, params, timeout=90):
        return CommandResult(type="result", id="x", ok=True, error=None, data={})


@pytest.fixture
def game(client, user, monkeypatch):
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", _Broker())
    headers = _login(client, user)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run {{SERVER_PORT}}")
    allocations = make_allocations(client, headers, node_id, 25001, 25001)
    body = {
        "name": "Game 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
    }
    created = client.post("/api/servers", json=body, headers=headers).json()
    url = f"/api/servers/{created['id']}"
    return SimpleNamespace(id=created["id"], headers=headers, url=url)


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _row(db_session, game) -> Server:
    return db_session.get(Server, uuid.UUID(game.id))


def _exit(db_session, game, code, status="running"):
    server = _row(db_session, game)
    server.status = status
    db_session.commit()
    frame = StateFrame(type="state", name=game.id, state="exited", exit_code=code)
    return apply_state(db_session, server.node_id, frame)


def _set(db_session, game, **fields):
    server = _row(db_session, game)
    for key, value in fields.items():
        setattr(server, key, value)
    db_session.commit()
    return server


def test_clean_exit_schedules_an_automatic_start(db_session, game):
    assert _exit(db_session, game, 0) == "offline"
    server = _row(db_session, game)
    remaining = (_utc(server.restart_due_at) - datetime.now(UTC)).total_seconds()
    assert 0 < remaining <= 30


def test_off_never_restarts(db_session, game):
    _set(db_session, game, auto_restart="off")
    _exit(db_session, game, 1)
    assert _row(db_session, game).restart_due_at is None


def test_crash_mode_ignores_a_clean_exit_but_not_a_crash(db_session, game):
    _set(db_session, game, auto_restart="crash")
    _exit(db_session, game, 0)
    assert _row(db_session, game).restart_due_at is None
    _exit(db_session, game, 139)
    assert _row(db_session, game).restart_due_at is not None


def test_a_stop_from_the_panel_is_not_restarted(db_session, game):
    assert _exit(db_session, game, 0, status="stopping") == "offline"
    assert _row(db_session, game).restart_due_at is None


def test_a_missing_start_command_is_not_restarted(db_session, game):
    _exit(db_session, game, 127)
    assert _row(db_session, game).restart_due_at is None


def test_stop_typed_in_the_console_is_not_restarted(db_session, game, monkeypatch):
    name = lifecycle.container_name(uuid.UUID(game.id))
    monkeypatch.setitem(hub._last_input, name, (time.monotonic(), "stop\n"))
    _exit(db_session, game, 0)
    assert _row(db_session, game).restart_due_at is None


def test_an_old_stop_input_does_not_count(db_session, game, monkeypatch):
    name = lifecycle.container_name(uuid.UUID(game.id))
    monkeypatch.setitem(hub._last_input, name, (time.monotonic() - 120, "stop\n"))
    _exit(db_session, game, 0)
    assert _row(db_session, game).restart_due_at is not None


def test_gives_up_after_repeated_quick_exits(db_session, game):
    _set(
        db_session,
        game,
        auto_restart_max_failures=2,
        last_auto_start_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    _exit(db_session, game, 1)
    server = _row(db_session, game)
    assert server.restart_failures == 1
    assert server.restart_due_at is not None
    assert _exit(db_session, game, 1) == "error"
    server = _row(db_session, game)
    assert server.restart_failures == 2
    assert server.restart_due_at is None
    assert "paused" in server.last_error


def test_a_long_run_resets_the_counter(db_session, game):
    _set(
        db_session,
        game,
        restart_failures=3,
        last_auto_start_at=datetime.now(UTC) - timedelta(hours=1),
    )
    _exit(db_session, game, 1)
    server = _row(db_session, game)
    assert server.restart_failures == 0
    assert server.restart_due_at is not None


def _due(db_session, game, **fields):
    return _set(
        db_session,
        game,
        status="offline",
        restart_due_at=datetime.now(UTC) - timedelta(seconds=1),
        **fields,
    )


def test_a_due_server_is_started(db_session, game):
    server = _due(db_session, game)
    calls = []

    async def start(db, row):
        calls.append(row.id)

    started = asyncio.run(auto_restart.run_due(db_session, start=start))
    assert started == [server.id]
    assert calls == [server.id]
    row = _row(db_session, game)
    assert row.restart_due_at is None
    assert row.last_auto_start_at is not None


def test_a_server_that_is_not_due_yet_is_left_alone(db_session, game):
    _set(
        db_session,
        game,
        status="offline",
        restart_due_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    calls = []

    async def start(db, row):
        calls.append(row.id)

    assert asyncio.run(auto_restart.run_due(db_session, start=start)) == []
    assert calls == []
    assert _row(db_session, game).restart_due_at is not None


def test_a_server_started_by_hand_is_not_started_again(db_session, game):
    _due(db_session, game)
    _set(db_session, game, status="running")
    calls = []

    async def start(db, row):
        calls.append(row.id)

    assert asyncio.run(auto_restart.run_due(db_session, start=start)) == []
    assert calls == []
    assert _row(db_session, game).restart_due_at is None


def test_switching_it_off_cancels_a_pending_start(db_session, game):
    _due(db_session, game, auto_restart="off")
    calls = []

    async def start(db, row):
        calls.append(row.id)

    asyncio.run(auto_restart.run_due(db_session, start=start))
    assert calls == []
    assert _row(db_session, game).restart_due_at is None


def test_an_offline_node_is_retried_without_counting(db_session, game):
    _due(db_session, game)

    async def start(db, row):
        raise HTTPException(409, "The node is offline.")

    asyncio.run(auto_restart.run_due(db_session, start=start))
    row = _row(db_session, game)
    assert row.restart_failures == 0
    assert row.restart_due_at is not None


def test_a_failing_start_counts_and_finally_gives_up(db_session, game):
    _due(db_session, game, auto_restart_max_failures=1)

    async def start(db, row):
        raise RuntimeError("boom")

    asyncio.run(auto_restart.run_due(db_session, start=start))
    row = _row(db_session, game)
    assert row.status == "error"
    assert row.restart_due_at is None
    assert "boom" in row.last_error


def test_settings_can_be_read_and_changed(client, game):
    body = client.get(game.url).json()
    assert body["auto_restart"] == "always"
    assert body["auto_restart_delay"] == 30
    assert body["auto_restart_max_failures"] == 5
    response = client.patch(
        game.url,
        json={"auto_restart": "crash", "auto_restart_delay": 300, "auto_restart_max_failures": 0},
        headers=game.headers,
    )
    assert response.status_code == 200, response.text
    changed = client.get(game.url).json()
    assert changed["auto_restart"] == "crash"
    assert changed["auto_restart_delay"] == 300
    assert changed["auto_restart_max_failures"] == 0
    bad = client.patch(game.url, json={"auto_restart": "sometimes"}, headers=game.headers)
    assert bad.status_code == 422
    too_fast = client.patch(game.url, json={"auto_restart_delay": 1}, headers=game.headers)
    assert too_fast.status_code == 422
