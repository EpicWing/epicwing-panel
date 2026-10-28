"""Protokoll zwischen Panel und Node-Agent (Version 1), siehe docs/agent-protocol.md."""

import base64
import uuid
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field

AUTH_CONTEXT = b"epicwing-agent-auth-v1\n"
NONCE_BYTES = 32
MAX_MESSAGE_CHARS = 16 * 1024
AUTH_TIMEOUT_SECONDS = 10
IDLE_TIMEOUT_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 90
# Der Agent installiert bis zu 30 Minuten (agent/docker.go), das Panel wartet länger.
INSTALL_COMMAND_TIMEOUT_SECONDS = 32 * 60
COMMAND_ACTIONS = (
    "container.create",
    "container.install",
    "container.start",
    "container.stop",
    "container.kill",
    "container.remove",
    "container.status",
    "console.watch",
    "console.unwatch",
    "console.input",
    "file.list",
    "file.read",
    "file.write",
    "file.mkdir",
    "file.rename",
    "file.decompress",
    "file.delete",
    "backup.create",
    "backup.restore",
    "backup.delete",
    "backup.status",
    "backup.read",
    "backup.copy",
)

WS_GOING_AWAY = 1001
WS_UNSUPPORTED = 1003
WS_POLICY_VIOLATION = 1008
WS_TOO_BIG = 1009
WS_REPLACED = 1012
# Der Agent wartet nur bei diesem Grund länger. Ein Reload von uvicorn sendet 1012 ohne Grund.
WS_REPLACED_REASON = "replaced"


class AuthMessage(BaseModel):
    type: Literal["auth"]
    node_id: uuid.UUID
    signature: str = Field(max_length=256)


class Heartbeat(BaseModel):
    type: Literal["heartbeat"]
    cpu_total: int = Field(ge=1, le=4096)
    ram_total_mb: int = Field(ge=1, le=100_000_000)
    disk_total_mb: int = Field(ge=1, le=1_000_000_000)
    cpu_percent: float = Field(ge=0, le=10_000)
    ram_used_mb: int = Field(ge=0, le=100_000_000)
    disk_used_mb: int = Field(ge=0, le=1_000_000_000)
    agent_version: str | None = Field(default=None, max_length=32)


def auth_message(node_id: uuid.UUID, nonce: bytes) -> bytes:
    """Das signierte Byte-Muster: Kontext, Node-ID als Text, Zeilenumbruch, rohe Nonce."""
    return AUTH_CONTEXT + str(node_id).encode() + b"\n" + nonce


def verify_signature(
    public_key_b64: str, node_id: uuid.UUID, nonce: bytes, signature_b64: str
) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True)
        )
        public_key.verify(
            base64.b64decode(signature_b64, validate=True), auth_message(node_id, nonce)
        )
    except (InvalidSignature, ValueError):
        return False
    return True


class CommandResult(BaseModel):
    type: Literal["result"]
    id: str = Field(min_length=1, max_length=64)
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=1024)


class ConsoleFrame(BaseModel):
    """Ausgabe eines Containers, vom Agent in Stücken geschickt."""

    type: Literal["console"]
    name: str = Field(min_length=1, max_length=64)
    data: str = Field(max_length=16_000)


class StateFrame(BaseModel):
    """Zustandswechsel eines Containers (auch der Abgleich beim Verbinden)."""

    type: Literal["state"]
    name: str = Field(min_length=1, max_length=64)
    state: Literal["running", "exited", "removed", "created"]
    exit_code: int | None = None


class StatsFrame(BaseModel):
    """Live resource counters for one managed container."""

    type: Literal["stats"]
    name: str = Field(min_length=1, max_length=64)
    cpu_percent: float = Field(ge=0, le=100_000)
    memory_used_bytes: int = Field(ge=0)
    memory_limit_bytes: int = Field(ge=0)
    disk_used_bytes: int = Field(ge=0)
    network_rx_bytes: int = Field(ge=0)
    network_tx_bytes: int = Field(ge=0)
    started_at: str | None = Field(default=None, max_length=64)
