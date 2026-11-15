"""Loads marketplace catalogs and packages from GitHub.

Only raw.githubusercontent.com is contacted, and only for repositories the admin
allowed in EPICWING_MARKETPLACE_REGISTRIES (comma separated owner/name list).
Packages are pinned to a commit, and the egg file is checked against its SHA-256.
"""

import hashlib
import json
import os
import posixpath
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas.marketplace import Index, IndexEntry, Manifest, valid_path, valid_repo

RAW_HOST = "https://raw.githubusercontent.com"
MAX_BYTES = 512 * 1024
TIMEOUT_SECONDS = 10
ENV_NAME = "EPICWING_MARKETPLACE_REGISTRIES"
REGISTRY_REF = "main"


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


def fetch_bytes(url: str) -> bytes:
    if not url.startswith(RAW_HOST + "/"):
        raise MarketplaceError("Only raw.githubusercontent.com is allowed.")
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise MarketplaceError(f"GitHub answered with status {response.status_code}.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise MarketplaceError("The file is too large.")
    except httpx.HTTPError:
        raise MarketplaceError("GitHub could not be reached.") from None
    return bytes(data)


def _json(url: str) -> Any:
    try:
        return json.loads(fetch_bytes(url).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MarketplaceError("The file is not valid JSON.") from None


def fetch_catalog(registry: str) -> list[IndexEntry]:
    if registry not in registries():
        raise MarketplaceError("This catalog is not allowed.")
    data = _json(raw_url(registry, REGISTRY_REF, "index.json"))
    try:
        return Index.model_validate(data).packages
    except ValidationError as exc:
        raise MarketplaceError(f"The catalog is invalid: {exc.errors()[0]['msg']}") from None


def fetch_manifest(entry: IndexEntry) -> Manifest:
    data = _json(raw_url(entry.repo, entry.commit, entry.path))
    try:
        manifest = Manifest.model_validate(data)
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
    try:
        egg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MarketplaceError("The egg file is not valid JSON.") from None
    if not isinstance(egg, dict):
        raise MarketplaceError("The egg file is not an egg.")
    return egg
