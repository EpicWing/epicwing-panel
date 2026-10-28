import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    location: Mapped[str] = mapped_column(String(64), default="")
    fqdn: Mapped[str | None] = mapped_column(String(255))
    # 'pending' bis sich ein Agent registriert hat.
    status: Mapped[str] = mapped_column(String(16), default="pending")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Hardwarewerte meldet später der Agent.
    cpu_total: Mapped[int | None] = mapped_column(Integer)
    ram_total_mb: Mapped[int | None] = mapped_column(Integer)
    disk_total_mb: Mapped[int | None] = mapped_column(Integer)
    agent_version: Mapped[str | None] = mapped_column(String(32))
    port_range_start: Mapped[int] = mapped_column(Integer)
    port_range_end: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NodeEnrollment(Base):
    __tablename__ = "node_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeCredential(Base):
    __tablename__ = "node_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), unique=True
    )
    # Roher Ed25519-Public-Key als Base64. Der private Schlüssel bleibt auf dem Node.
    public_key: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
