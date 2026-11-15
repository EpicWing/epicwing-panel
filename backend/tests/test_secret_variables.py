import importlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import ServerVariable
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login
from tests.test_server_power import FakeBroker

TOKEN = "MTIzNDU2.abcdef.super-secret-bot-token"


@pytest.fixture
def broker(monkeypatch):
    fake = FakeBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


@pytest.fixture
def bot(client, user, broker):
    """A server whose egg has one secret variable (TOKEN) and one normal one (MAIN_FILE)."""
    headers = _login(client, user)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(
        client,
        headers,
        nest_id,
        name="Bot",
        variables=[
            {"name": "Token", "env_variable": "TOKEN", "secret": True},
            {"name": "Main file", "env_variable": "MAIN_FILE", "default_value": "bot.py"},
        ],
    )
    allocations = make_allocations(client, headers, node_id, 25001, 25001)
    body = {
        "name": "Bot 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
        "variables": {"TOKEN": TOKEN},
    }
    response = client.post("/api/servers", json=body, headers=headers)
    assert response.status_code == 201, response.text
    created = response.json()
    return SimpleNamespace(
        id=created["id"],
        egg_id=egg_id,
        headers=headers,
        url=f"/api/servers/{created['id']}",
        created=response,
    )


def _stored(db_session, bot, env="TOKEN"):
    db_session.expire_all()
    return db_session.scalar(
        select(ServerVariable.value).where(
            ServerVariable.server_id == uuid.UUID(bot.id), ServerVariable.env_variable == env
        )
    )


def _creates(broker):
    return [params for action, params in broker.calls if action == "container.create"]


def test_egg_keeps_the_secret_flag(client, bot):
    egg = client.get(f"/api/eggs/{bot.egg_id}", headers=bot.headers).json()
    flags = {v["env_variable"]: v["secret"] for v in egg["variables"]}
    assert flags == {"TOKEN": True, "MAIN_FILE": False}


def test_secret_is_stored_encrypted(client, bot, db_session):
    stored = _stored(db_session, bot)
    assert stored.startswith("enc:")
    assert TOKEN not in stored
    # A normal variable stays as it is.
    assert _stored(db_session, bot, "MAIN_FILE") == "bot.py"


def test_api_never_returns_the_secret(client, bot):
    responses = [
        bot.created,
        client.get(bot.url, headers=bot.headers),
        client.get("/api/servers", headers=bot.headers),
        client.get(bot.url + "/startup", headers=bot.headers),
    ]
    for response in responses:
        assert response.status_code == 200 or response.status_code == 201
        assert TOKEN not in response.text
        assert "enc:" not in response.text

    server = client.get(bot.url, headers=bot.headers).json()
    assert "TOKEN" not in server["variables"]
    assert server["variables"]["MAIN_FILE"] == "bot.py"
    assert server["secrets_set"] == ["TOKEN"]

    startup = client.get(bot.url + "/startup", headers=bot.headers).json()
    token = next(v for v in startup["variables"] if v["env_variable"] == "TOKEN")
    assert token["secret"] is True
    assert token["secret_set"] is True
    assert token["value"] == ""


def test_the_container_gets_the_plain_token(client, bot, broker):
    assert client.post(bot.url + "/install", headers=bot.headers).status_code == 200
    started = client.post(bot.url + "/power", json={"action": "start"}, headers=bot.headers)
    assert started.status_code == 200, started.text

    creates = _creates(broker)
    # install, and the container that is created again on start
    assert len(creates) == 2
    for params in creates:
        assert params["env"]["TOKEN"] == TOKEN
        assert params["env"]["MAIN_FILE"] == "bot.py"


def test_changing_the_secret_updates_storage_and_container(client, bot, broker, db_session):
    response = client.patch(
        bot.url, json={"variables": {"TOKEN": "new-token"}}, headers=bot.headers
    )
    assert response.status_code == 200, response.text
    assert "new-token" not in response.text

    stored = _stored(db_session, bot)
    assert stored.startswith("enc:")
    assert "new-token" not in stored

    client.post(bot.url + "/install", headers=bot.headers)
    assert _creates(broker)[0]["env"]["TOKEN"] == "new-token"


def test_clearing_the_secret(client, bot, broker, db_session):
    response = client.patch(bot.url, json={"variables": {"TOKEN": ""}}, headers=bot.headers)
    assert response.status_code == 200, response.text
    assert _stored(db_session, bot) == ""
    assert client.get(bot.url, headers=bot.headers).json()["secrets_set"] == []


def test_old_plain_text_value_still_works(client, bot, broker, db_session):
    """A value stored before this feature (no enc: prefix) is still passed on."""
    row = db_session.scalar(
        select(ServerVariable).where(
            ServerVariable.server_id == uuid.UUID(bot.id), ServerVariable.env_variable == "TOKEN"
        )
    )
    row.value = "old-plain-token"
    db_session.commit()

    client.post(bot.url + "/install", headers=bot.headers)
    assert _creates(broker)[0]["env"]["TOKEN"] == "old-plain-token"
    assert "old-plain-token" not in client.get(bot.url, headers=bot.headers).text
