import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InstalledPackage(Base):
    """A marketplace package that was installed (for now always as an egg)."""

    __tablename__ = "marketplace_packages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    package_id: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(48))
    category: Mapped[str] = mapped_column(String(32))
    repository: Mapped[str] = mapped_column(String(201))
    commit: Mapped[str] = mapped_column(String(40))
    egg_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("eggs.id", ondelete="SET NULL"))
    installed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ServerPackage(Base):
    """A plugin or mod from the marketplace that was copied into a server."""

    __tablename__ = "server_packages"
    __table_args__ = (
        UniqueConstraint("server_id", "package_id", name="uq_server_packages_server_package"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True
    )
    package_id: Mapped[str] = mapped_column(String(63))
    registry: Mapped[str] = mapped_column(String(201))
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(48))
    category: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
