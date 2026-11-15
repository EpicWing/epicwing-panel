import base64
import hashlib
import json
import uuid

import pytest

from app.models import Server
from tests import test_marketplace_api as market_tests
from tests import test_server_power as power
from tests.test_server_files import FileBroker

server = power.server
shop = market_tests.shop
_fresh_catalog_cache = market_tests._fresh_catalog_cache

JAR = b"PK\x03\x04 not really a jar " * 50000  # about 1.1 MB, so it takes several writes


@pytest.fixture
def broker(monkeypatch):
    import importlib

    fake = FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


@pytest.fixture
def ready(db_session, server):
    row = db_session.get(Server, uuid.UUID(server.id))
    row.status = "offline"
    db_session.commit()
    return server


def _plugin(shop, **file_changes):
    file = {
        "path": "LuckPerms.jar",
        "sha256": hashlib.sha256(JAR).hexdigest(),
        "name": "LuckPerms-5.4.jar",
        **file_changes,
    }
    manifest = market_tests.manifest_body(
        b"", id="luckperms", name="LuckPerms", category="plugin", game="minecraft",
        egg=None, file=file,
    )
    raw = json.dumps(manifest).encode()
    shop.put("luckperms/manifest.json", raw)
    shop.put("luckperms/LuckPerms.jar", JAR)
    entry = {
        **shop.entry,
        "id": "luckperms",
        "name": "LuckPerms",
        "category": "plugin",
        "game": "minecraft",
        "path": "luckperms/manifest.json",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    market_tests._put_index(shop, [entry, shop.entry])


def _install(client, server, package_id="luckperms"):
    return client.post(
        f"/api/marketplace/servers/{server.id}",
        json={"registry": market_tests.REPO, "package_id": package_id},
        headers=server.headers,
    )


def test_plugin_is_copied_into_the_server(client, ready, broker, shop):
    _plugin(shop)
    response = _install(client, ready)
    assert response.status_code == 200, response.text
    assert response.json() == {"path": "plugins/LuckPerms-5.4.jar", "size": len(JAR)}
    actions = [action for action, _params in broker.calls]
    assert actions[0] == "file.mkdir" and actions[-2:] == ["file.delete", "file.rename"]
    writes = [params for action, params in broker.calls if action == "file.write"]
    assert len(writes) == 3
    assert b"".join(base64.b64decode(w["data"]) for w in writes) == JAR
    assert {w["path"] for w in writes} == {"plugins/LuckPerms-5.4.jar.part"}
    assert writes[0]["truncate"] and not writes[1]["truncate"]
    assert broker.calls[-1][1]["to"] == "plugins/LuckPerms-5.4.jar"


def test_custom_target_folder(client, ready, broker, shop):
    _plugin(shop, target="oxide/plugins")
    response = _install(client, ready)
    assert response.json()["path"] == "oxide/plugins/LuckPerms-5.4.jar"
    mkdirs = [params["path"] for action, params in broker.calls if action == "file.mkdir"]
    assert mkdirs == ["oxide", "oxide/plugins"]


def test_a_wrong_checksum_writes_nothing(client, ready, broker, shop):
    _plugin(shop, sha256="0" * 64)
    response = _install(client, ready)
    assert response.status_code == 502
    assert broker.calls == []


def test_eggs_are_not_copied_into_a_server(client, ready, broker, shop):
    _plugin(shop)
    assert _install(client, ready, "discord-bot-python").status_code == 422
    assert broker.calls == []


def test_servers_without_install_are_refused(client, server, broker, shop):
    _plugin(shop)
    assert _install(client, server).status_code == 409
    assert broker.calls == []
