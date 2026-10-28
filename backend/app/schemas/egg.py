import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.schemas.node import NAME_RE

IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9._/:@-]{0,254}")
ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
MAX_SCRIPT_CHARS = 65_535


def clean_name(value: str) -> str:
    value = value.strip()
    if not NAME_RE.fullmatch(value):
        raise ValueError(
            "The name must be 1 to 64 characters and may only contain letters, "
            "digits, spaces, dots, underscores and hyphens."
        )
    return value


def clean_text(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"At most {limit} characters, no control characters.")
    return value


def clean_image(value: str) -> str:
    value = value.strip()
    if not IMAGE_RE.fullmatch(value):
        raise ValueError("The image reference is invalid.")
    return value


def clean_env_name(value: str) -> str:
    value = value.strip()
    if not ENV_RE.fullmatch(value):
        raise ValueError(
            "The variable name may only contain uppercase letters, digits and underscores."
        )
    return value


def clean_script(value: str) -> str:
    if len(value) > MAX_SCRIPT_CHARS or "\x00" in value:
        raise ValueError("The script is too long or contains a NUL byte.")
    return value.replace("\r\n", "\n")


# Welches Feld wie geprüft wird, bestimmt der Feldname.
CLEANERS: dict[str, Callable[[str], str]] = {
    "name": clean_name,
    "description": lambda v: clean_text(v, 255),
    "docker_image": clean_image,
    "image": clean_image,
    "startup": lambda v: clean_text(v, 2048),
    "stop_command": lambda v: clean_text(v, 255),
    "install_script": clean_script,
    "env_variable": clean_env_name,
    "default_value": lambda v: clean_text(v, 1024),
}


class CleanedFields(BaseModel):
    """Basisklasse: prüft und bereinigt Textfelder anhand ihres Namens."""

    @field_validator("*", check_fields=False)
    @classmethod
    def _clean_fields(cls, value: Any, info: ValidationInfo) -> Any:
        cleaner = CLEANERS.get(info.field_name or "")
        if cleaner is None or value is None:
            return value
        return cleaner(value)


def reject_nulls(model: BaseModel, fields: tuple[str, ...]) -> None:
    """Bei Teiländerungen darf ein mitgeschicktes Feld nicht null sein."""
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} must not be null.")


class NestCreate(CleanedFields):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""


class NestUpdate(CleanedFields):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        reject_nulls(self, ("name", "description"))
        return self


class NestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    egg_count: int = 0
    created_at: datetime


class EggVariableIn(CleanedFields):
    model_config = ConfigDict(extra="forbid")

    name: str
    env_variable: str
    default_value: str = ""
    description: str = ""
    user_editable: bool = True


class EggVariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    env_variable: str
    default_value: str
    description: str
    user_editable: bool


def _check_unique_env(variables: list[EggVariableIn] | None) -> None:
    if variables is None:
        return
    names = [v.env_variable for v in variables]
    if len(set(names)) != len(names):
        raise ValueError("A variable name is listed more than once.")


class EggCreate(CleanedFields):
    model_config = ConfigDict(extra="forbid")

    nest_id: uuid.UUID
    name: str
    description: str = ""
    docker_image: str
    startup: str = ""
    stop_command: str = ""
    install_script: str = ""
    variables: list[EggVariableIn] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_unique_env(self.variables)
        return self


class EggUpdate(CleanedFields):
    """Teilweise Änderung. Wird variables mitgeschickt, ersetzt es die ganze Liste."""

    model_config = ConfigDict(extra="forbid")

    nest_id: uuid.UUID | None = None
    name: str | None = None
    description: str | None = None
    docker_image: str | None = None
    startup: str | None = None
    stop_command: str | None = None
    install_script: str | None = None
    variables: list[EggVariableIn] | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> Self:
        reject_nulls(self, tuple(type(self).model_fields))
        _check_unique_env(self.variables)
        return self


class EggOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nest_id: uuid.UUID
    nest_name: str = ""
    name: str
    description: str
    docker_image: str
    startup: str
    stop_command: str
    install_script: str
    variables: list[EggVariableOut] = []
    created_at: datetime
