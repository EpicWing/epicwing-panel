import json
import re
import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agentlink.protocol import COMMAND_ACTIONS

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME_RE = re.compile(rf"(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*")


class NodeCreate(BaseModel):
    name: str
    location: str = ""
    fqdn: str | None = None
    # Default range, if nothing is given when creating.
    port_range_start: int = Field(default=1024, ge=1024, le=65535)
    port_range_end: int = Field(default=65535, ge=1024, le=65535)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not NAME_RE.fullmatch(value):
            raise ValueError(
                "The name must be 1 to 64 characters and may only contain letters, "
                "digits, spaces, dots, underscores and hyphens."
            )
        return value

    @field_validator("location")
    @classmethod
    def _check_location(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 64 or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid location: max. 64 characters, no control characters.")
        return value

    @field_validator("fqdn")
    @classmethod
    def _check_fqdn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            return None
        if not HOSTNAME_RE.fullmatch(value):
            raise ValueError("The hostname is invalid.")
        return value

    @model_validator(mode="after")
    def _check_ports(self) -> Self:
        if self.port_range_start > self.port_range_end:
            raise ValueError("The port range is invalid: the start must not be after the end.")
        return self


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: str
    fqdn: str | None
    status: str
    last_heartbeat_at: datetime | None
    cpu_total: int | None
    ram_total_mb: int | None
    disk_total_mb: int | None
    ram_limit_mb: int | None = None
    disk_limit_mb: int | None = None
    agent_version: str | None
    port_range_start: int
    port_range_end: int
    created_at: datetime


class EnrollmentOut(BaseModel):
    token: str
    expires_at: datetime


class NodeCreated(BaseModel):
    node: NodeOut
    enrollment: EnrollmentOut


def _validate_name(value: str) -> str:
    value = value.strip()
    if not NAME_RE.fullmatch(value):
        raise ValueError(
            "The name must be 1 to 64 characters and may only contain letters, "
            "digits, spaces, dots, underscores and hyphens."
        )
    return value


def _validate_location(value: str) -> str:
    value = value.strip()
    if len(value) > 64 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid location: max. 64 characters, no control characters.")
    return value


def _validate_fqdn(value: str) -> str | None:
    value = value.strip().lower()
    if not value:
        return None
    if not HOSTNAME_RE.fullmatch(value):
        raise ValueError("The hostname is invalid.")
    return value


class NodeUpdate(BaseModel):
    """Partial update. Only fields that are sent are changed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    location: str | None = None
    fqdn: str | None = None
    port_range_start: int | None = Field(default=None, ge=1024, le=65535)
    port_range_end: int | None = Field(default=None, ge=1024, le=65535)
    # None setzt das Limit zurück auf unbegrenzt
    ram_limit_mb: int | None = Field(default=None, ge=1, le=100_000_000)
    disk_limit_mb: int | None = Field(default=None, ge=1, le=100_000_000)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_name(value)

    @field_validator("location")
    @classmethod
    def _check_location(cls, value: str | None) -> str | None:
        return None if value is None else _validate_location(value)

    @field_validator("fqdn")
    @classmethod
    def _check_fqdn(cls, value: str | None) -> str | None:
        return None if value is None else _validate_fqdn(value)

    @model_validator(mode="after")
    def _check(self) -> Self:
        for field in ("name", "location", "port_range_start", "port_range_end"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null.")
        start, end = self.port_range_start, self.port_range_end
        if start is not None and end is not None and start > end:
            raise ValueError("The port range is invalid: the start must not be after the end.")
        return self


class NodeDetail(NodeOut):
    connected: bool
    fingerprint: str | None
    registered_at: datetime | None
    cpu_percent: float | None
    ram_used_mb: int | None
    disk_used_mb: int | None
    history: list[dict[str, float]] = []


CONTAINER_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}")
CREATE_PARAMS = {"name", "image", "ports", "env", "memory_mb", "cpus"}
INSTALL_PARAMS = {"name", "image", "env", "memory_mb", "cpus", "install_script"}
MAX_PARAMS_CHARS = 12_000


class CommandRequest(BaseModel):
    """Command for the agent of a node. The agent also checks the parameters itself."""

    model_config = ConfigDict(extra="forbid")

    action: str
    params: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.action not in COMMAND_ACTIONS:
            raise ValueError("Unknown action.")
        if self.action == "container.create":
            wanted = CREATE_PARAMS
        elif self.action == "container.install":
            wanted = INSTALL_PARAMS
        else:
            wanted = {"name"}
        if set(self.params) != wanted:
            raise ValueError(f"The params must be exactly: {', '.join(sorted(wanted))}.")
        name = self.params["name"]
        if not isinstance(name, str) or not CONTAINER_NAME_RE.fullmatch(name):
            raise ValueError("Invalid container name.")
        if self.action == "container.install":
            script = self.params["install_script"]
            if not isinstance(script, str) or not script or len(script) > 65_535:
                raise ValueError("Invalid install script.")
        if len(json.dumps(self.params)) > MAX_PARAMS_CHARS:
            raise ValueError("The params are too large.")
        return self


class CommandOut(BaseModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
