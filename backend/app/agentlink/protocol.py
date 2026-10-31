"""Protocol between panel and node agent (version 1), see docs/agent-protocol.md."""

import base64
import uuid
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field

AUTH_CONTEXT = b"epicwing-agent-auth-v1\n"
NONCE_BYTES = 32
MAX_MESSAGE_CHARS = 16 * 1024
# Frames from the agent after login (file chunks in Base64), same size as maxMessageBytes.
MAX_FRAME_CHARS = 1024 * 1024
AUTH_TIMEOUT_SECONDS = 10
IDLE_TIMEOUT_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 90
# The agent installs for up to 30 minutes (agent/docker.go), the panel waits longer.
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
    "transfer.ticket",
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
# The agent waits longer only for this reason. A uvicorn reload sends 1012 without a reason.
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
    # Stable error code from the agent (e.g. PORT_IN_USE). Older agents do not send one.
    code: str | None = Field(default=None, max_length=64)


class ConsoleFrame(BaseModel):
    """Output of a container, sent by the agent in chunks."""

    type: Literal["console"]
    name: str = Field(min_length=1, max_length=64)
    data: str = Field(max_length=16_000)


class StateFrame(BaseModel):
    """State change of a container (also the sync when connecting)."""

    type: Literal["state"]
    name: str = Field(min_length=1, max_length=64)
    state: Literal["running", "exited", "removed", "created"]
    exit_code: int | None = None


# Packet and protocol counters an agent may add to a stats frame (cumulative values).
STATS_NET_KEYS = frozenset(
    {
        "rx_packets",
        "rx_errors",
        "rx_dropped",
        "tx_packets",
        "tx_errors",
        "tx_dropped",
        "ip_in_receives",
        "ip_in_hdr_errors",
        "ip_in_addr_errors",
        "ip_reasm_reqds",
        "icmp_in_msgs",
        "icmp_in_echos",
        "tcp_in_segs",
        "tcp_passive_opens",
        "tcp_attempt_fails",
        "tcp_estab_resets",
        "tcp_in_errs",
        "tcp_syncookies_sent",
        "tcp_listen_overflows",
        "tcp_listen_drops",
        "udp_in_datagrams",
        "udp_no_ports",
        "udp_in_errors",
        "udp_rcvbuf_errors",
    }
)

# Console line counters of the last measuring window (see agent/consoleflood.go).
STATS_CONSOLE_KEYS = frozenset({"lines", "window_lines", "sources", "top"})


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
    net: dict[str, Any] | None = None
    console: dict[str, Any] | None = None
