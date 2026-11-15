"""Loads marketplace catalogs and packages from GitHub.

Only raw.githubusercontent.com is contacted, and only for repositories the admin
allowed in EPICWING_MARKETPLACE_REGISTRIES (comma separated owner/name list).
The catalog (index.json) carries everything the list needs, so browsing never
loads single packages. A manifest is fetched only for one package, when it is
previewed or installed, and is checked against the checksum from the catalog.
"""

import hashlib
import json
import logging
import os
import posixpath
import threading
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas.marketplace import Index, IndexEntry, Manifest, valid_path, valid_repo

log = logging.getLogger(__name__)

RAW_HOST = "https://raw.githubusercontent.com"
MAX_BYTES = 512 * 1024
INDEX_MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 10
INDEX_TIMEOUT_SECONDS = 30
CACHE_SECONDS = 15 * 60
ENV_NAME = "EPICWING_MARKETPLACE_REGISTRIES"
REGISTRY_REF = "main"

_cache: dict[str, tuple[float, list[IndexEntry]]] = {}
_lock = threading.Lock()


class MarketplaceError(Exception):
    """A readable problem with the catalog or a package."""


def registries() -> list[str]:
    """The catalogs the admin allowed. Invalid entries are skipped."""
    found = [part.strip() for part in os.environ.get(ENV_NAME, "").split(",")]
    return [repo for repo in found if repo and valid_repo(repo)]


def raw_url(repo: str, ref: str, path: str) -> str:
    # The pieces are checked again here, so a bad value can never change the host or path.
    if not valid_repo(repo) or not valid_path(ref) or not valid_path(path):
        raise MarketplaceError("The address of the file is invalid.")
    return f"{RAW_HOST}/{repo}/{ref}/{path}"


def fetch_bytes(url: str, max_bytes: int = MAX_BYTES, timeout: int = TIMEOUT_SECONDS) -> bytes:
    if not url.startswith(RAW_HOST + "/"):
        raise MarketplaceError("Only raw.githubusercontent.com is allowed.")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise MarketplaceError(f"GitHub answered with status {response.status_code}.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise MarketplaceError("The file is too large.")
    except httpx.HTTPError:
        raise MarketplaceError("GitHub could not be reached.") from None
    return bytes(data)


def _parse(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MarketplaceError("The file is not valid JSON.") from None


def _download_catalog(registry: str) -> list[IndexEntry]:
    url = raw_url(registry, REGISTRY_REF, "index.json")
    data = _parse(fetch_bytes(url, INDEX_MAX_BYTES, INDEX_TIMEOUT_SECONDS))
    try:
        index = Index.model_validate(data)
    except ValidationError as exc:
        raise MarketplaceError(f"The catalog is invalid: {exc.errors()[0]['msg']}") from None
    entries: list[IndexEntry] = []
    seen: set[str] = set()
    skipped = 0
    # A broken entry is skipped, it never makes the whole catalog unusable.
    for raw in index.packages:
        try:
            entry = IndexEntry.model_validate(raw)
        except ValidationError:
            skipped += 1
            continue
        if entry.id in seen:
            skipped += 1
            continue
        seen.add(entry.id)
        entries.append(entry)
    if skipped:
        log.warning("Marketplace catalog %s: %d invalid entries skipped", registry, skipped)
    return entries


def fetch_catalog(registry: str, force: bool = False) -> list[IndexEntry]:
    """The entries of a catalog, cached for a few minutes."""
    if registry not in registries():
        raise MarketplaceError("This catalog is not allowed.")
    with _lock:
        cached = _cache.get(registry)
    if cached and not force and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        entries = _download_catalog(registry)
    except MarketplaceError:
        if cached:
            log.warning("Marketplace catalog %s could not be refreshed, using old copy", registry)
            return cached[1]
        raise
    with _lock:
        _cache[registry] = (time.monotonic(), entries)
    return entries


def fetch_manifest(entry: IndexEntry) -> Manifest:
    raw = fetch_bytes(raw_url(entry.repo, entry.commit, entry.path))
    if hashlib.sha256(raw).hexdigest() != entry.manifest_sha256:
        raise MarketplaceError("The package does not match the checksum of the catalog.")
    try:
        manifest = Manifest.model_validate(_parse(raw))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise MarketplaceError(f"The package is invalid ({where}): {first['msg']}") from None
    if manifest.id != entry.id:
        raise MarketplaceError("The package id does not match the catalog.")
    if manifest.repository.lower() != entry.repo.lower():
        raise MarketplaceError("The package belongs to a different repository.")
    return manifest


def fetch_egg(entry: IndexEntry, manifest: Manifest) -> dict[str, Any]:
    """The egg file of a package (Pterodactyl format), checked against its checksum."""
    if manifest.egg is None:
        raise MarketplaceError("This package has no egg file.")
    folder = posixpath.dirname(entry.path)
    path = posixpath.join(folder, manifest.egg.path) if folder else manifest.egg.path
    raw = fetch_bytes(raw_url(entry.repo, entry.commit, path))
    if hashlib.sha256(raw).hexdigest() != manifest.egg.sha256:
        raise MarketplaceError("The egg file does not match its checksum.")
    egg = _parse(raw)
    if not isinstance(egg, dict):
        raise MarketplaceError("The egg file is not an egg.")
    return egg
