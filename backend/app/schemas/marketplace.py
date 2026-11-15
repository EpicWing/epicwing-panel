"""Package format of the marketplace (manifest.json) and the catalog (index.json)."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.egg import clean_text

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
VERSION_RE = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}(?:-[0-9A-Za-z.-]{1,32})?")
PATH_RE = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")

Category = Literal["egg", "bot-template", "plugin", "docker-template"]
# These categories deliver an egg. The others are listed, but cannot be installed yet.
INSTALLABLE: frozenset[str] = frozenset({"egg", "bot-template"})


def valid_repo(value: str) -> bool:
    return bool(REPO_RE.fullmatch(value)) and not any(p in {".", ".."} for p in value.split("/"))


def valid_path(value: str) -> bool:
    return bool(PATH_RE.fullmatch(value)) and not any(p in {".", ".."} for p in value.split("/"))


class FileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not valid_path(value):
            raise ValueError("The file path is invalid.")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha(cls, value: str) -> str:
        value = value.lower()
        if not SHA256_RE.fullmatch(value):
            raise ValueError("The SHA-256 checksum is invalid.")
        return value


class Manifest(BaseModel):
    # Unknown fields are ignored, so newer packages still load in an older panel.
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[1]
    id: str
    name: str
    description: str = ""
    version: str
    author: str
    category: Category
    repository: str
    license: str
    # Which view a server of this package gets (planned, ignored by the panel for now).
    ui_profile: str | None = Field(default=None, max_length=32)
    egg: FileRef | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not SLUG_RE.fullmatch(value):
            raise ValueError("The id may only use a-z, 0-9 and hyphens (2 to 63 characters).")
        return value

    @field_validator("name", "author", "license")
    @classmethod
    def _short(cls, value: str) -> str:
        value = clean_text(value, 64)
        if not value:
            raise ValueError("This field must not be empty.")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return clean_text(value, 255)

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not VERSION_RE.fullmatch(value):
            raise ValueError("The version must look like 1.2.3.")
        return value

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str) -> str:
        if not valid_repo(value):
            raise ValueError("The repository must be owner/name.")
        return value

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.category in INSTALLABLE and self.egg is None:
            raise ValueError("This category needs an egg file.")
        return self


MAX_INDEX_PACKAGES = 20000
TAG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")


class IndexEntry(BaseModel):
    """One line of the catalog. It holds everything the list needs."""

    model_config = ConfigDict(extra="ignore")

    id: str
    repo: str
    commit: str
    path: str = "manifest.json"
    manifest_sha256: str
    name: str
    description: str = ""
    version: str
    author: str
    license: str
    category: Category
    tags: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not SLUG_RE.fullmatch(value):
            raise ValueError("The package id is invalid.")
        return value

    @field_validator("repo")
    @classmethod
    def _repo(cls, value: str) -> str:
        if not valid_repo(value):
            raise ValueError("The repository must be owner/name.")
        return value

    @field_validator("commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        value = value.lower()
        if not COMMIT_RE.fullmatch(value):
            raise ValueError("Packages must be pinned to a full 40 character commit.")
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not valid_path(value):
            raise ValueError("The manifest path is invalid.")
        return value

    @field_validator("manifest_sha256")
    @classmethod
    def _sha(cls, value: str) -> str:
        value = value.lower()
        if not SHA256_RE.fullmatch(value):
            raise ValueError("The SHA-256 checksum is invalid.")
        return value

    @field_validator("name", "author", "license")
    @classmethod
    def _short(cls, value: str) -> str:
        value = clean_text(value, 64)
        if not value:
            raise ValueError("This field must not be empty.")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return clean_text(value, 255)

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not VERSION_RE.fullmatch(value):
            raise ValueError("The version must look like 1.2.3.")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return [t for t in (v.strip().lower() for v in value) if TAG_RE.fullmatch(t)]


class Index(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[2]
    # Entries are validated one by one by the service, so one bad entry does not hide the rest.
    packages: list[dict] = Field(max_length=MAX_INDEX_PACKAGES)
