import importlib
from datetime import UTC, datetime

import pytest

from app.services.schedules import next_run, zone_name
from tests import test_server_files, test_server_power as base

server = base.server


@pytest.fixture
def broker(monkeypatch):
    fake = test_server_files.FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def test_cron_runs_in_the_panel_time_zone(monkeypatch):
    monkeypatch.setenv("EPICWING_TIMEZONE", "Europe/Berlin")
    summer = next_run("0 6 * * *", datetime(2026, 10, 18, 12, 0, tzinfo=UTC))
    assert summer == datetime(2026, 10, 19, 4, 0, tzinfo=UTC)
    winter = next_run("0 6 * * *", datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    assert winter == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)


def test_unknown_zone_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("EPICWING_TIMEZONE", "Nowhere/Land")
    assert zone_name() == "UTC"
    result = next_run("0 4 * * *", datetime(2026, 10, 18, 12, 0, tzinfo=UTC))
    assert result == datetime(2026, 10, 19, 4, 0, tzinfo=UTC)


def test_api_reports_the_time_zone(client, server):
    response = client.post(
        server.url + "/schedules",
        json={"name": "Daily restart", "minute": "0", "hour": "4"},
        headers=server.headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["timezone"] == "UTC"
