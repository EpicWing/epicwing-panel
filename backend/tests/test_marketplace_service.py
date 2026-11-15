import hashlib
import json

import pytest

from app.schemas.marketplace import IndexEntry, Manifest
from app.services import marketplace as mp

REPO = "EpicWing/marketplace"
COMMIT = "a" * 40
EGG = json.dumps({"meta": {"version": "PTDL_v2"}, "name": "Bot"}).encode()


def manifest_body(**changes):
    body = {
        "schema_version": 1,
        "id": "discord-bot-python",
        "name": "Discord Bot Python",
        "description": "A bot",
        "version": "1.0.0",
        "author": "EpicWing",
        "category": "bot-template",
        "repository": REPO,
        "license": "MIT",
        "egg": {"path": "egg.json", "sha256": hashlib.sha256(EGG).hexdigest()},
    }
    body.update(changes)
    return body


def manifest_raw(**changes) -> bytes:
    return json.dumps(manifest_body(**changes)).encode()


def entry_body(raw=None, **changes):
    raw = manifest_raw() if raw is None else raw
    body = {
        "id": "discord-bot-python",
        "repo": REPO,
        "commit": COMMIT,
        "path": "discord-bot-python/manifest.json",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "name": "Discord Bot Python",
        "description": "A bot",
        "version": "1.0.0",
        "author": "EpicWing",
        "license": "MIT",
        "category": "bot-template",
        "tags": [],
    }
    body.update(changes)
    return body


def make_entry(raw=None, **changes):
    return IndexEntry(**entry_body(raw, **changes))


@pytest.fixture(autouse=True)
def _fresh_cache():
    mp._cache.clear()
    yield
    mp._cache.clear()


@pytest.fixture
def remote(monkeypatch):
    files: dict[str, bytes] = {}
    calls: list[str] = []

    def fake(url, *_args, **_kwargs):
        calls.append(url)
        if url not in files:
            raise mp.MarketplaceError("not found")
        return files[url]

    monkeypatch.setattr(mp, "fetch_bytes", fake)
    files["calls"] = calls  # type: ignore[assignment]
    return files


def put(files, path, data, ref=COMMIT):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    files[mp.raw_url(REPO, ref, path)] = raw


def put_index(files, packages, version=2):
    put(files, "index.json", {"schema_version": version, "packages": packages}, ref=mp.REGISTRY_REF)


def test_registries_come_from_the_environment(monkeypatch):
    monkeypatch.delenv(mp.ENV_NAME, raising=False)
    assert mp.registries() == []
    monkeypatch.setenv(mp.ENV_NAME, "EpicWing/marketplace, bad, ../x/y, other/repo")
    assert mp.registries() == ["EpicWing/marketplace", "other/repo"]


def test_raw_url_rejects_traversal_and_odd_input():
    assert mp.raw_url(REPO, COMMIT, "a/manifest.json").startswith(mp.RAW_HOST + "/")
    for repo, ref, path in [
        ("a/..", COMMIT, "m.json"),
        ("../a/b", COMMIT, "m.json"),
        (REPO, COMMIT, "../m.json"),
        (REPO, COMMIT, "/m.json"),
        (REPO, "x/../y", "m.json"),
        ("evil.com/a@b", COMMIT, "m.json"),
    ]:
        with pytest.raises(mp.MarketplaceError):
            mp.raw_url(repo, ref, path)


def test_only_github_raw_is_contacted():
    with pytest.raises(mp.MarketplaceError):
        mp.fetch_bytes("https://evil.example/index.json")
    with pytest.raises(mp.MarketplaceError):
        mp.fetch_bytes("http://raw.githubusercontent.com/a/b/c/d.json")


def test_catalog_needs_an_allowed_registry(monkeypatch, remote):
    monkeypatch.delenv(mp.ENV_NAME, raising=False)
    with pytest.raises(mp.MarketplaceError):
        mp.fetch_catalog(REPO)


def test_catalog_is_loaded(monkeypatch, remote):
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    put_index(remote, [entry_body()])
    entries = mp.fetch_catalog(REPO)
    assert [e.id for e in entries] == ["discord-bot-python"]
    assert entries[0].name == "Discord Bot Python"


def test_old_catalog_format_is_refused(monkeypatch, remote):
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    put_index(remote, [entry_body()], version=1)
    with pytest.raises(mp.MarketplaceError, match="invalid"):
        mp.fetch_catalog(REPO)


def test_a_broken_entry_does_not_hide_the_others(monkeypatch, remote):
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    unpinned = entry_body(id="x-bot", commit="main")
    no_sum = entry_body(id="y-bot")
    del no_sum["manifest_sha256"]
    duplicate = entry_body(name="Copy")
    put_index(remote, [entry_body(), unpinned, no_sum, duplicate])
    entries = mp.fetch_catalog(REPO)
    assert [e.id for e in entries] == ["discord-bot-python"]
    assert entries[0].name == "Discord Bot Python"


def test_catalog_is_cached_and_can_be_refreshed(monkeypatch, remote):
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    put_index(remote, [entry_body()])
    mp.fetch_catalog(REPO)
    mp.fetch_catalog(REPO)
    assert len(remote["calls"]) == 1
    mp.fetch_catalog(REPO, force=True)
    assert len(remote["calls"]) == 2


def test_old_copy_is_used_when_a_refresh_fails(monkeypatch, remote):
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    put_index(remote, [entry_body()])
    mp.fetch_catalog(REPO)
    del remote[mp.raw_url(REPO, mp.REGISTRY_REF, "index.json")]
    assert [e.id for e in mp.fetch_catalog(REPO, force=True)] == ["discord-bot-python"]


def test_manifest_and_egg_roundtrip(remote):
    raw = manifest_raw()
    entry = make_entry(raw)
    put(remote, entry.path, raw)
    put(remote, "discord-bot-python/egg.json", EGG)
    manifest = mp.fetch_manifest(entry)
    assert manifest.name == "Discord Bot Python"
    assert mp.fetch_egg(entry, manifest)["name"] == "Bot"


def test_manifest_must_match_the_catalog(remote):
    raw = manifest_raw(id="another-bot")
    entry = make_entry(raw)
    put(remote, entry.path, raw)
    with pytest.raises(mp.MarketplaceError, match="id"):
        mp.fetch_manifest(entry)
    raw = manifest_raw(repository="someone/else")
    entry = make_entry(raw)
    put(remote, entry.path, raw)
    with pytest.raises(mp.MarketplaceError, match="repository"):
        mp.fetch_manifest(entry)


def test_manifest_with_a_wrong_checksum_is_refused(remote):
    entry = make_entry()
    put(remote, entry.path, manifest_raw(description="changed"))
    with pytest.raises(mp.MarketplaceError, match="checksum"):
        mp.fetch_manifest(entry)


def test_egg_with_a_wrong_checksum_is_refused(remote):
    raw = manifest_raw()
    entry = make_entry(raw)
    put(remote, entry.path, raw)
    put(remote, "discord-bot-python/egg.json", EGG + b" ")
    manifest = mp.fetch_manifest(entry)
    with pytest.raises(mp.MarketplaceError, match="checksum"):
        mp.fetch_egg(entry, manifest)


def test_manifest_rules():
    assert Manifest.model_validate(manifest_body()).version == "1.0.0"
    # Unknown fields are ignored.
    assert Manifest.model_validate(manifest_body(future_field=1)).id == "discord-bot-python"
    for changes in [
        {"id": "Bad Id"},
        {"version": "latest"},
        {"repository": "not-a-repo"},
        {"category": "virus"},
        {"egg": None},
        {"egg": {"path": "../egg.json", "sha256": "0" * 64}},
        {"egg": {"path": "egg.json", "sha256": "xyz"}},
        {"name": ""},
    ]:
        with pytest.raises(ValueError):
            Manifest.model_validate(manifest_body(**changes))
    # Categories that cannot be installed yet need no egg.
    plugin = manifest_body(category="plugin", game="minecraft", egg=None)
    assert Manifest.model_validate(plugin).egg is None


def test_commit_must_be_a_full_hash():
    for commit in ["main", "abc123", "A" * 41, "g" * 40]:
        with pytest.raises(ValueError):
            make_entry(commit=commit)
    assert make_entry(commit="A" * 40).commit == "a" * 40


def test_entry_rules():
    for changes in [
        {"manifest_sha256": "xyz"},
        {"version": "latest"},
        {"category": "virus"},
        {"name": ""},
        {"path": "../manifest.json"},
    ]:
        with pytest.raises(ValueError):
            make_entry(**changes)
    # Bad tags are dropped, good ones are kept in lower case.
    assert make_entry(tags=["Game", "bad tag!", "mc"]).tags == ["game", "mc"]
