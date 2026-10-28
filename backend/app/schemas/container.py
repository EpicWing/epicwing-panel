import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.node import NAME_RE

IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9._/:@-]{0,254}")


class ContainerCreate(BaseModel):
    """Neuer Container. Der Agent prüft Image und Ports zusätzlich selbst."""

    model_config = ConfigDict(extra="forbid")

    node_id: uuid.UUID
    name: str
    image: str
    host_port: int = Field(ge=1024, le=65535)
    container_port: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    memory_mb: int = Field(default=256, ge=16, le=65536)
    cpus: float = Field(default=0.5, ge=0.1, le=64)

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

    @field_validator("image")
    @classmethod
    def _check_image(cls, value: str) -> str:
        value = value.strip()
        if not IMAGE_RE.fullmatch(value):
            raise ValueError("The image reference is invalid.")
        return value


class ContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    node_name: str = ""
    name: str
    docker_name: str
    image: str
    host_port: int
    container_port: int
    protocol: str
    memory_mb: int
    cpus: float
    status: str
    last_error: str | None
    created_at: datetime
