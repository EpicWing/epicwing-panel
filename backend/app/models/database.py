import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DatabaseHost(Base):
    """MariaDB/MySQL-Instanz, auf der die Datenbanken der Server angelegt werden."""

    __tablename__ = "database_hosts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=3306)
    admin_user: Mapped[str] = mapped_column(String(64))
    # Verschlüsselt über app.security.vault, nie im Klartext gespeichert.
    admin_password: Mapped[str] = mapped_column(Text)
    max_databases: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServerDatabase(Base):
    __tablename__ = "server_databases"
    __table_args__ = (
        UniqueConstraint("host_id", "name", name="uq_server_databases_host_name"),
        UniqueConstraint("host_id", "username", name="uq_server_databases_host_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("database_hosts.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(32))
    remote: Mapped[str] = mapped_column(String(255), default="%")
    # Verschlüsselt, damit das Panel das Passwort wie bei Pyrodactyl anzeigen kann.
    password: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
