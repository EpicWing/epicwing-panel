import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
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
