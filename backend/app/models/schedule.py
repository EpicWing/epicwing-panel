import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Schedule(Base):
    """Ein Zeitplan eines Servers. Die Zeiten sind Cron-Felder in UTC."""

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    cron_minute: Mapped[str] = mapped_column(String(32), default="*")
    cron_hour: Mapped[str] = mapped_column(String(32), default="*")
    cron_day_of_month: Mapped[str] = mapped_column(String(32), default="*")
    cron_month: Mapped[str] = mapped_column(String(32), default="*")
    cron_day_of_week: Mapped[str] = mapped_column(String(32), default="*")
    only_when_online: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(16))
    last_detail: Mapped[str | None] = mapped_column(String(300))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScheduleTask(Base):
    """Eine Aufgabe in einem Zeitplan. Die Aufgaben laufen nacheinander nach sequence."""

    __tablename__ = "schedule_tasks"
    __table_args__ = (
        UniqueConstraint("schedule_id", "sequence", name="uq_schedule_tasks_schedule_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    # power, command oder backup
    action: Mapped[str] = mapped_column(String(16))
    # Bei power: start, stop, restart, kill. Bei command: der Befehl. Bei backup: leer.
    payload: Mapped[str] = mapped_column(String(1024), default="")
    # Wartezeit in Sekunden, bevor diese Aufgabe startet.
    time_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    continue_on_failure: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
