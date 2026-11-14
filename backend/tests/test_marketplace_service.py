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


def make_entry(**changes):
    body = {
        "id": "discord-bot-python",
        "repo": REPO,
        "commit": COMMIT,
        "path": "discord-bot-python/manifest.json",
    }
    body.update(changes)
    return IndexEntry(**body)


@pytest.fixture
def remote(monkeypatch):
    files: dict[str, bytes] = {}

    def fake(url):
        if url not in files:
            raise mp.MarketplaceError("not found")
        return files[url]

    monkeypatch.setattr(mp, "fetch_bytes", fake)
    return files


def put(files, path, data, ref=COMMIT):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    files[mp.raw_url(REPO, ref, path)] = raw


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
    put(
        remote,
        "index.json",
        {"schema_version": 1, "packages": [make_entry().model_dump()]},
        ref=mp.REGISTRY_REF,
    )
    entries = mp.fetch_catalog(REPO)
    assert [e.id for e in entries] == ["discord-bot-python"]


def test_catalog_refuses_unpinned_packages(monkeypatch, remote):
    monkeypatch.setenv(mp.ENV_NAME, REPO)
    bad = {"id": "x-bot", "repo": REPO, "commit": "main"}
    put(remote, "index.json", {"schema_version": 1, "packages": [bad]}, ref=mp.REGISTRY_REF)
    with pytest.raises(mp.MarketplaceError, match="commit"):
        mp.fetch_catalog(REPO)


def test_manifest_and_egg_roundtrip(remote):
    entry = make_entry()
    put(remote, entry.path, manifest_body())
    put(remote, "discord-bot-python/egg.json", EGG)
    manifest = mp.fetch_manifest(entry)
    assert manifest.name == "Discord Bot Python"
    assert mp.fetch_egg(entry, manifest)["name"] == "Bot"


def test_manifest_must_match_the_catalog(remote):
    entry = make_entry()
    put(remote, entry.path, manifest_body(id="another-bot"))
    with pytest.raises(mp.MarketplaceError, match="id"):
        mp.fetch_manifest(entry)
    put(remote, entry.path, manifest_body(repository="someone/else"))
    with pytest.raises(mp.MarketplaceError, match="repository"):
        mp.fetch_manifest(entry)


def test_egg_with_a_wrong_checksum_is_refused(remote):
    entry = make_entry()
    put(remote, entry.path, manifest_body())
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
    assert Manifest.model_validate(manifest_body(category="plugin", egg=None)).egg is None


def test_commit_must_be_a_full_hash():
    for commit in ["main", "abc123", "A" * 41, "g" * 40]:
        with pytest.raises(ValueError):
            make_entry(commit=commit)
    assert make_entry(commit="A" * 40).commit == "a" * 40
