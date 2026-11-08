import pytest

from app.services import dbhost

ENDPOINT = dbhost.Endpoint("db.example.test", 3306, "root", "secret")


def _create():
    dbhost.create_database(ENDPOINT, "shop_1", "u0123456789ab", "%", "pw")


def test_failed_create_does_not_drop_an_existing_database(monkeypatch):
    calls = []

    def fake_run(endpoint, statements):
        calls.append([sql for sql, _args in statements])
        raise dbhost.HostError("rejected")

    monkeypatch.setattr(dbhost, "_run", fake_run)
    with pytest.raises(dbhost.HostError):
        _create()
    assert len(calls) == 1
    assert not any("DROP" in sql for sql in calls[0])


def test_failed_user_step_removes_what_was_created(monkeypatch):
    calls = []

    def fake_run(endpoint, statements):
        calls.append([sql for sql, _args in statements])
        if len(calls) == 2:
            raise dbhost.HostError("rejected")

    monkeypatch.setattr(dbhost, "_run", fake_run)
    with pytest.raises(dbhost.HostError):
        _create()
    assert len(calls) == 3
    assert any("DROP DATABASE" in sql for sql in calls[2])
