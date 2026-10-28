import re
import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME_RE = re.compile(rf"(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*")


class NodeCreate(BaseModel):
    name: str
    location: str = ""
    fqdn: str | None = None
    port_range_start: int = Field(ge=1024, le=65535)
    port_range_end: int = Field(ge=1024, le=65535)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not NAME_RE.fullmatch(value):
            raise ValueError(
                "Der Name muss 1 bis 64 Zeichen lang sein und darf nur Buchstaben, "
                "Ziffern, Leerzeichen, Punkt, Unterstrich und Bindestrich enthalten."
            )
        return value

    @field_validator("location")
    @classmethod
    def _check_location(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 64 or any(ord(c) < 32 for c in value):
            raise ValueError("Der Standort darf höchstens 64 Zeichen ohne Steuerzeichen haben.")
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
            raise ValueError("Der Hostname ist ungültig.")
        return value

    @model_validator(mode="after")
    def _check_ports(self) -> Self:
        if self.port_range_start > self.port_range_end:
            raise ValueError("Der Port-Bereich ist ungültig: Start muss vor dem Ende liegen.")
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
