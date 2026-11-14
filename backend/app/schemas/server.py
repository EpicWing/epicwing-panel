import ipaddress
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.egg import CLEANERS, ENV_RE, CleanedFields, clean_text, reject_nulls

MAX_PORTS_PER_REQUEST = 500
# 0 means unlimited, otherwise this is the lowest value.
MINIMUMS = {"memory_mb": 16, "cpus": 0.1, "disk_mb": 100}


def clean_server_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 64 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("The name must be 1 to 64 characters without control characters.")
    return value


SERVER_CLEANERS = {**CLEANERS, "name": clean_server_name}


def _zero_or_min(value: Any, field: str) -> Any:
    if value is not None and 0 < value < MINIMUMS[field]:
        raise ValueError(f"{field} must be 0 (unlimited) or at least {MINIMUMS[field]}.")
    return value


class AllocationCreate(BaseModel):
    """One port or a range from port_start to port_end on an IP."""

    model_config = ConfigDict(extra="forbid")

    ip: str
    port_start: int = Field(ge=1024, le=65535)
    port_end: int | None = Field(default=None, ge=1024, le=65535)

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, value: str) -> str:
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            raise ValueError("The IP address is invalid.") from None

    @model_validator(mode="after")
    def _check_ports(self) -> Self:
        if self.port_end is None:
            self.port_end = self.port_start
        if self.port_end < self.port_start:
            raise ValueError("The port range is invalid: the start must not be after the end.")
        if self.port_end - self.port_start + 1 > MAX_PORTS_PER_REQUEST:
            raise ValueError(f"At most {MAX_PORTS_PER_REQUEST} ports per request.")
        return self


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    ip: str
    port: int
    server_id: uuid.UUID | None
    server_name: str | None = None
    is_primary: bool


class AllocationRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ip: str
    port: int
    is_primary: bool


def _clean_variables(value: dict[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return None
    for key in value:
        if not ENV_RE.fullmatch(key):
            raise ValueError(f"Invalid variable name: {key}.")
    return {key: clean_text(text, 1024) for key, text in value.items()}


class ServerCreate(CleanedFields):
    cleaners: ClassVar[dict[str, Callable[[str], str]]] = SERVER_CLEANERS
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    owner_id: uuid.UUID
    node_id: uuid.UUID
    egg_id: uuid.UUID
    allocation_id: uuid.UUID
    extra_allocation_ids: list[uuid.UUID] = Field(default_factory=list, max_length=15)
    memory_mb: int = Field(default=1024, ge=0, le=65536)
    cpus: float = Field(default=1.0, ge=0, le=64)
    disk_mb: int = Field(default=5120, ge=0, le=10_000_000)
    # Without a value, the image and start command of the egg apply.
    image: str | None = None
    startup: str | None = None
    variables: dict[str, str] = Field(default_factory=dict, max_length=64)

    @field_validator("memory_mb", "cpus", "disk_mb")
    @classmethod
    def _limits(cls, value: Any, info: Any) -> Any:
        return _zero_or_min(value, info.field_name)

    @field_validator("variables")
    @classmethod
    def _check_variables(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_variables(value) or {}

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [self.allocation_id, *self.extra_allocation_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("An allocation is listed more than once.")
        return self


class ServerUpdate(CleanedFields):
    cleaners: ClassVar[dict[str, Callable[[str], str]]] = SERVER_CLEANERS
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    memory_mb: int | None = Field(default=None, ge=0, le=65536)
    cpus: float | None = Field(default=None, ge=0, le=64)
    disk_mb: int | None = Field(default=None, ge=0, le=10_000_000)
    image: str | None = None
    startup: str | None = None
    variables: dict[str, str] | None = Field(default=None, max_length=64)
    backup_limit: int | None = Field(default=None, ge=0, le=1000)
    auto_restart: str | None = Field(default=None, pattern="^(off|crash|always)$")
    auto_restart_delay: int | None = Field(default=None, ge=5, le=3600)
    auto_restart_max_failures: int | None = Field(default=None, ge=0, le=100)

    @field_validator("memory_mb", "cpus", "disk_mb")
    @classmethod
    def _limits(cls, value: Any, info: Any) -> Any:
        return _zero_or_min(value, info.field_name)

    @field_validator("variables")
    @classmethod
    def _check_variables(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _clean_variables(value)

    @model_validator(mode="after")
    def _check(self) -> Self:
        reject_nulls(self, tuple(type(self).model_fields))
        return self


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    owner_id: uuid.UUID
    node_id: uuid.UUID
    node_name: str = ""
    egg_id: uuid.UUID
    egg_name: str = ""
    image: str
    startup: str
    startup_command: str = ""
    memory_mb: int
    cpus: float
    disk_mb: int
    backup_limit: int = 0
    auto_restart: str = "always"
    auto_restart_delay: int = 30
    auto_restart_max_failures: int = 5
    restart_due_at: datetime | None = None
    status: str
    last_error: str | None
    allocations: list[AllocationRef] = []
    variables: dict[str, str] = {}
    secrets_set: list[str] = []
    permissions: list[str] = []
    live_cpu_percent: float | None = None
    live_memory_used_bytes: int | None = None
    live_disk_used_bytes: int | None = None
    live_network_rx_bytes: int | None = None
    live_network_tx_bytes: int | None = None
    created_at: datetime
