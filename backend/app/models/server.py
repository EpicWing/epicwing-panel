import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
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
