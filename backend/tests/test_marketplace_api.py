import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import marketplace as mp
from tests.factories import make_allocations
from tests.test_nodes_detail import _create, _login

REPO = "EpicWing/marketplace"
COMMIT = "b" * 40
FOLDER = "discord-bot-python"

EGG = {
    "meta": {"version": "PTDL_v2"},
    "name": "Marketplace Bot",
    "description": "A bot",
    "docker_images": {"Python 3.12": "ghcr.io/ptero-eggs/yolks:python_3.12"},
    "startup": "python {{MAIN_FILE}}",
    "config": {"stop": "^C"},
    "scripts": {"installation": {"script": "#!/bin/ash\necho hi\n", "entrypoint": "ash"}},
    "variables": [
        {
            "name": "Main file",
            "env_variable": "MAIN_FILE",
            "default_value": "bot.py",
            "rules": "required|string|max:128",
        },
        {
            "name": "Discord token",
            "env_variable": "DISCORD_TOKEN",
            "default_value": "",
            "rules": "nullable|string|max:255",
            "secret": True,
        },
    ],
}


def manifest_body(egg_bytes, **changes):
    body = {
        "schema_version": 1,
        "id": "discord-bot-python",
        "name": "Marketplace Bot",
        "description": "A bot",
        "version": "1.0.0",
        "author": "EpicWing",
        "category": "bot-template",
        "repository": REPO,
        "license": "MIT",
        "egg": {"path": "egg.json", "sha256": hashlib.sha256(egg_bytes).hexdigest()},
    }
    body.update(changes)
    return body


@pytest.fixture(autouse=True)
def _fresh_catalog_cache():
    mp._cache.clear()
    yield
    mp._cache.clear()


@pytest.fixture
def shop(monkeypatch):
    """A fake GitHub with one catalog and one package."""
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    files: dict[str, bytes] = {}

    def fake(url, *_args, **_kwargs):
        if url not in files:
            raise mp.MarketplaceError("GitHub answered with status 404.")
        return files[url]

    monkeypatch.setattr(mp, "fetch_bytes", fake)

    def put(path, data, ref=COMMIT):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        files[mp.raw_url(REPO, ref, path)] = raw

    egg_bytes = json.dumps(EGG).encode()
    manifest_bytes = json.dumps(manifest_body(egg_bytes)).encode()
    entry = {
        "id": "discord-bot-python",
        "repo": REPO,
        "commit": COMMIT,
        "path": f"{FOLDER}/manifest.json",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "name": "Marketplace Bot",
        "description": "A bot",
        "version": "1.0.0",
        "author": "EpicWing",
        "license": "MIT",
        "category": "bot-template",
        "tags": [],
    }
    put("index.json", {"schema_version": 2, "packages": [entry]}, ref=mp.REGISTRY_REF)
    put(f"{FOLDER}/manifest.json", manifest_bytes)
    put(f"{FOLDER}/egg.json", egg_bytes)
    return SimpleNamespace(put=put, egg_bytes=egg_bytes, entry=entry)


@pytest.fixture
def headers(client, user):
    return _login(client, user)


def _install(client, headers, **changes):
    body = {"registry": REPO, "package_id": "discord-bot-python", **changes}
    return client.post("/api/marketplace/install", json=body, headers=headers)


def _eggs(client, headers):
    return client.get("/api/eggs", headers=headers).json()


def test_catalog_needs_login():
    assert TestClient(app).get("/api/marketplace").status_code == 401


def test_catalog_is_empty_without_registries(client, headers, monkeypatch):
    monkeypatch.delenv(mp.ENV_NAME, raising=False)
    body = client.get("/api/marketplace", headers=headers).json()
    assert body["registries"] == []
    assert body["packages"] == []


def test_catalog_lists_the_package(client, headers, shop):
    body = client.get("/api/marketplace", headers=headers).json()
    assert body["errors"] == []
    [package] = body["packages"]
    assert package["id"] == "discord-bot-python"
    assert package["installable"] is True
    assert package["installed"] is False
    assert package["commit"] == COMMIT


def _put_index(shop, entries):
    shop.put("index.json", {"schema_version": 2, "packages": entries}, ref=mp.REGISTRY_REF)


def test_catalog_skips_a_broken_entry_and_goes_on(client, headers, shop):
    broken = {**shop.entry, "id": "bad-bot", "commit": "main"}
    _put_index(shop, [broken, shop.entry])
    body = client.get("/api/marketplace", headers=headers).json()
    assert [p["id"] for p in body["packages"]] == ["discord-bot-python"]
    assert body["total"] == 1


def test_catalog_search_category_and_pages(client, headers, shop):
    games = [
        {**shop.entry, "id": f"game-{n}", "name": f"Game {n}", "category": "egg", "tags": ["game"]}
        for n in range(5)
    ]
    _put_index(shop, [shop.entry, *games])

    def get(**params):
        return client.get("/api/marketplace", params=params, headers=headers).json()

    page = get(limit=2, offset=0)
    assert page["total"] == 6
    assert [p["name"] for p in page["packages"]] == ["Game 0", "Game 1"]
    assert [p["name"] for p in get(limit=2, offset=4)["packages"]] == ["Game 4", "Marketplace Bot"]
    assert get(q="game")["total"] == 5
    assert get(q="GAME 3")["total"] == 1
    assert get(category="bot-template")["total"] == 1
    assert get(q="zzz")["total"] == 0


def test_broken_manifest_is_refused_on_preview(client, headers, shop):
    shop.put(f"{FOLDER}/manifest.json", {"schema_version": 1, "id": "oops"})
    ref = {"registry": REPO, "package_id": "discord-bot-python"}
    response = client.post("/api/marketplace/preview", json=ref, headers=headers)
    assert response.status_code == 502
    assert "checksum" in response.json()["detail"]


def test_preview_shows_the_egg_without_installing(client, headers, shop):
    ref = {"registry": REPO, "package_id": "discord-bot-python"}
    response = client.post("/api/marketplace/preview", json=ref, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["docker_image"] == "ghcr.io/ptero-eggs/yolks:python_3.12"
    assert body["startup"] == "python {{MAIN_FILE}}"
    assert "echo hi" in body["install_script"]
    secrets = {v["env_variable"]: v["secret"] for v in body["variables"]}
    assert secrets == {"MAIN_FILE": False, "DISCORD_TOKEN": True}
    assert _eggs(client, headers) == []


def test_install_creates_the_egg_and_keeps_the_secret_flag(client, headers, shop):
    response = _install(client, headers)
    assert response.status_code == 201, response.text
    [egg] = _eggs(client, headers)
    assert egg["name"] == "Marketplace Bot"
    assert egg["nest_name"] == "Marketplace"
    flags = {v["env_variable"]: v["secret"] for v in egg["variables"]}
    assert flags == {"MAIN_FILE": False, "DISCORD_TOKEN": True}

    body = client.get("/api/marketplace", headers=headers).json()
    assert body["packages"][0]["installed"] is True
    assert [p["package_id"] for p in body["installed"]] == ["discord-bot-python"]
    assert _install(client, headers).status_code == 409


def test_changed_egg_file_is_refused(client, headers, shop):
    shop.put(f"{FOLDER}/egg.json", shop.egg_bytes + b" ")
    assert _install(client, headers).status_code == 502
    assert _eggs(client, headers) == []


def test_unknown_package_is_not_found(client, headers, shop):
    assert _install(client, headers, package_id="nope-bot").status_code == 404


def test_packages_that_are_not_eggs_cannot_be_installed(client, headers, shop):
    raw = json.dumps(manifest_body(shop.egg_bytes, category="plugin", egg=None)).encode()
    shop.put(f"{FOLDER}/manifest.json", raw)
    entry = {
        **shop.entry,
        "category": "plugin",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    _put_index(shop, [entry])
    assert _install(client, headers).status_code == 422
    assert _eggs(client, headers) == []


def test_remove_deletes_the_egg_and_the_record(client, headers, shop):
    record = _install(client, headers).json()
    assert (
        client.delete(f"/api/marketplace/installed/{record['id']}", headers=headers).status_code
        == 204
    )
    assert _eggs(client, headers) == []
    assert client.get("/api/marketplace", headers=headers).json()["installed"] == []


def test_remove_is_refused_while_a_server_uses_the_egg(client, user, headers, shop):
    record = _install(client, headers).json()
    node_id = _create(client, headers)
    [allocation] = make_allocations(client, headers, node_id, 25001, 25001)
    body = {
        "name": "Bot 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": record["egg_id"],
        "allocation_id": allocation,
    }
    assert client.post("/api/servers", json=body, headers=headers).status_code == 201
    response = client.delete(f"/api/marketplace/installed/{record['id']}", headers=headers)
    assert response.status_code == 409
    assert len(_eggs(client, headers)) == 1


def _names(client, headers, **params):
    body = client.get("/api/marketplace", params=params, headers=headers).json()
    return [p["name"] for p in body["packages"]]


def test_catalog_sort_filter_and_facets(client, headers, shop):
    base = shop.entry
    a = {**base, "id": "a-bot", "name": "A Bot", "author": "Ann", "downloads": 10,
         "updated_at": "2026-01-01", "tags": ["admin", "tools"]}
    b = {**base, "id": "b-bot", "name": "B Bot", "author": "Bob", "downloads": 500,
         "updated_at": "2026-03-01", "tags": ["tools"]}
    c = {**base, "id": "c-bot", "name": "C Bot", "author": "Bob",
         "updated_at": "2026-02-01", "tags": []}
    _put_index(shop, [a, b, c])

    assert _names(client, headers, sort="popular") == ["B Bot", "A Bot", "C Bot"]
    assert _names(client, headers, sort="newest") == ["B Bot", "C Bot", "A Bot"]
    assert _names(client, headers, sort="newest", order="asc") == ["A Bot", "C Bot", "B Bot"]
    assert _names(client, headers, sort="name") == ["A Bot", "B Bot", "C Bot"]
    assert _names(client, headers, sort="name", order="desc") == ["C Bot", "B Bot", "A Bot"]
    assert _names(client, headers, tag=["tools"]) == ["B Bot", "A Bot"]
    assert _names(client, headers, tag=["admin", "tools"]) == ["A Bot"]
    assert _names(client, headers, author="BOB") == ["B Bot", "C Bot"]

    body = client.get("/api/marketplace", params={"author": "Ann"}, headers=headers).json()
    assert body["tag_options"] == [{"value": "tools", "count": 2}, {"value": "admin", "count": 1}]
    assert body["author_options"] == [{"value": "Bob", "count": 2}, {"value": "Ann", "count": 1}]
    [package] = body["packages"]
    assert package["downloads"] == 10
    assert package["updated_at"] == "2026-01-01"


def test_catalog_refuses_an_unknown_sort(client, headers, shop):
    response = client.get("/api/marketplace", params={"sort": "random"}, headers=headers)
    assert response.status_code == 422


def test_catalog_game_loader_and_version(client, headers, shop):
    base = shop.entry
    paper = {**base, "id": "essentials", "name": "Essentials", "category": "plugin",
             "game": "minecraft", "loaders": ["paper", "Spigot"], "game_versions": ["1.21", "1.20.6"]}
    fabric = {**base, "id": "sodium", "name": "Sodium", "category": "mod",
              "game": "minecraft", "loaders": ["fabric"], "game_versions": ["1.21"]}
    oxide = {**base, "id": "kits", "name": "Kits", "category": "plugin",
             "game": "rust", "loaders": ["oxide"]}
    _put_index(shop, [paper, fabric, oxide])

    assert _names(client, headers, game="minecraft", sort="name") == ["Essentials", "Sodium"]
    assert _names(client, headers, loader="spigot") == ["Essentials"]
    assert _names(client, headers, version="1.20.6") == ["Essentials"]
    assert _names(client, headers, category="plugin", game="rust") == ["Kits"]

    body = client.get("/api/marketplace", params={"category": "plugin"}, headers=headers).json()
    assert body["game_options"] == [{"value": "minecraft", "count": 1}, {"value": "rust", "count": 1}]
    assert body["version_options"][0] == {"value": "1.21", "count": 1}
    assert all(p["installable"] is False for p in body["packages"])


def test_old_category_names_still_work(client, headers, shop):
    _put_index(shop, [{**shop.entry, "id": "old-game", "name": "Old Game", "category": "egg"}])
    body = client.get("/api/marketplace", params={"category": "game"}, headers=headers).json()
    assert [p["category"] for p in body["packages"]] == ["game"]
    assert _names(client, headers, category="egg") == ["Old Game"]
