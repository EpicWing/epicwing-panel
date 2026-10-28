import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Allocation(Base):
    """IP und Port auf einer Node. Gehört zu höchstens einem Server."""

    __tablename__ = "allocations"
    __table_args__ = (
        UniqueConstraint("node_id", "ip", "port", name="uq_allocations_node_ip_port"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    ip: Mapped[str] = mapped_column(String(45))
    port: Mapped[int] = mapped_column(Integer)
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("servers.id", ondelete="SET NULL"), index=True
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Server(Base):
    __tablename__ = "servers"

    # Die ID dient später auch als Name des Datenverzeichnisses auf der Node.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="RESTRICT"), index=True
    )
    egg_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eggs.id", ondelete="RESTRICT"), index=True
    )
    # Werte aus dem Egg, pro Server überschreibbar.
    image: Mapped[str] = mapped_column(String(255))
    startup: Mapped[str] = mapped_column(String(2048), default="")
    memory_mb: Mapped[int] = mapped_column(Integer)
    cpus: Mapped[float] = mapped_column(Float)
    disk_mb: Mapped[int] = mapped_column(Integer)
    # 0 heißt unbegrenzt viele Backups.
    backup_limit: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Neustart, wenn der Server von selbst endet: off, crash (nur Absturz) oder always.
    auto_restart: Mapped[str] = mapped_column(String(8), default="always", server_default="always")
    auto_restart_delay: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    auto_restart_max_failures: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5"
    )
    restart_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    restart_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_auto_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 'new' heißt: nur im Panel angelegt, noch nichts auf der Node. Die übrigen Werte
    # (installing, offline, starting, running, stopping, error) setzt die Agent-Anbindung.
    status: Mapped[str] = mapped_column(String(16), default="new")
    last_error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ServerVariable(Base):
    __tablename__ = "server_variables"

    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )
    env_variable: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024), default="")


class ServerMember(Base):
    """Ein Benutzer mit eigenen Rechten auf einem Server. Der Besitzer steht nicht hier."""

    __tablename__ = "server_members"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_server_members_server_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ServerMemberPermission(Base):
    __tablename__ = "server_member_permissions"

    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("server_members.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)


class ServerBackup(Base):
    """Ein Backup eines Servers. Die Datei liegt auf der Node, hier nur die Metadaten."""

    __tablename__ = "server_backups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(128))
    # running, ok oder failed
    status: Mapped[str] = mapped_column(String(16), default="running")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    sha256: Mapped[str | None] = mapped_column(String(64))
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    ignored: Mapped[str] = mapped_column(Text, default="", server_default="")
    error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
