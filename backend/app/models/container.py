import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Container(Base):
    __tablename__ = "containers"
    __table_args__ = (
        UniqueConstraint("node_id", "host_port", "protocol", name="uq_containers_node_port"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    # Anzeigename im Panel. Der Docker-Name wird vom Panel erzeugt (ew- plus Kurz-ID).
    name: Mapped[str] = mapped_column(String(64))
    docker_name: Mapped[str] = mapped_column(String(63), unique=True)
    image: Mapped[str] = mapped_column(String(255))
    host_port: Mapped[int] = mapped_column(Integer)
    container_port: Mapped[int] = mapped_column(Integer)
    protocol: Mapped[str] = mapped_column(String(3), default="tcp")
    memory_mb: Mapped[int] = mapped_column(Integer)
    cpus: Mapped[float] = mapped_column(Float)
    # creating, created, running, stopped oder error.
    status: Mapped[str] = mapped_column(String(16), default="creating")
    last_error: Mapped[str | None] = mapped_column(String(1024))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
