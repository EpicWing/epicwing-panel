"""Zeitpläne eines Servers: Liste, Anlegen, Aufgaben, Löschen und sofort ausführen."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.backups import BackupCreate
from app.api.servers import POWER_PERMISSION
from app.db import get_db
from app.models import Schedule, ScheduleTask, Server
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import audit, schedule_runner
from app.services.schedules import POWER_ACTIONS, build_expression, next_run, zone_name

router = APIRouter(prefix="/servers", tags=["schedules"])

DbSession = Annotated[Session, Depends(get_db)]
SchedulesView = Annotated[ServerAccess, Depends(server_access(ServerPermission.SCHEDULES_VIEW))]
SchedulesManage = Annotated[
    ServerAccess, Depends(server_access(ServerPermission.SCHEDULES_MANAGE))
]

MAX_SCHEDULES = 20
MAX_TASKS = 10
MAX_OFFSET_SECONDS = 900
CRON_FIELDS = {
    "minute": "cron_minute",
    "hour": "cron_hour",
    "day_of_month": "cron_day_of_month",
    "month": "cron_month",
    "day_of_week": "cron_day_of_week",
}


def _no_control(value: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Control characters are not allowed.")
    return value


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("The name is empty.")
    return _no_control(value)


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    minute: str = Field("*", max_length=32)
    hour: str = Field("*", max_length=32)
    day_of_month: str = Field("*", max_length=32)
    month: str = Field("*", max_length=32)
    day_of_week: str = Field("*", max_length=32)
    only_when_online: bool = True
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)

    @model_validator(mode="after")
    def _cron(self) -> "ScheduleCreate":
        build_expression(self.minute, self.hour, self.day_of_month, self.month, self.day_of_week)
        return self


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=64)
    minute: str | None = Field(None, max_length=32)
    hour: str | None = Field(None, max_length=32)
    day_of_month: str | None = Field(None, max_length=32)
    month: str | None = Field(None, max_length=32)
    day_of_week: str | None = Field(None, max_length=32)
    only_when_online: bool | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["power", "command", "backup"]
    payload: str = Field("", max_length=1024)
    time_offset: int = Field(0, ge=0, le=MAX_OFFSET_SECONDS)
    continue_on_failure: bool = False

    @model_validator(mode="after")
    def _check(self) -> "TaskCreate":
        payload = self.payload.strip()
        if self.action == "power":
            if payload not in POWER_ACTIONS:
                raise ValueError("Choose start, stop, restart or kill.")
        elif self.action == "command":
            if not payload:
                raise ValueError("The command is empty.")
            _no_control(payload)
        else:
            _no_control(payload)
            try:
                BackupCreate(ignored=payload)
            except ValidationError:
                raise ValueError("The ignore list is not valid.") from None
        self.payload = payload
        return self


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    action: str
    payload: str
    time_offset: int
    continue_on_failure: bool


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    minute: str
    hour: str
    day_of_month: str
    month: str
    day_of_week: str
    only_when_online: bool
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    is_running: bool
    last_result: str | None = None
    last_detail: str | None = None
    timezone: str = "UTC"
    tasks: list[TaskOut]


def _expression(row: Schedule) -> str:
    return build_expression(
        row.cron_minute,
        row.cron_hour,
        row.cron_day_of_month,
        row.cron_month,
        row.cron_day_of_week,
    )


def _out(db: Session, row: Schedule) -> ScheduleOut:
    tasks = db.scalars(
        select(ScheduleTask)
        .where(ScheduleTask.schedule_id == row.id)
        .order_by(ScheduleTask.sequence)
    ).all()
    return ScheduleOut(
        id=row.id,
        name=row.name,
        minute=row.cron_minute,
        hour=row.cron_hour,
        day_of_month=row.cron_day_of_month,
        month=row.cron_month,
        day_of_week=row.cron_day_of_week,
        only_when_online=row.only_when_online,
        enabled=row.enabled,
        last_run_at=row.last_run_at,
        next_run_at=row.next_run_at,
        is_running=schedule_runner.is_running(row.id),
        last_result=row.last_result,
        last_detail=row.last_detail,
        timezone=zone_name(),
        tasks=[TaskOut.model_validate(task) for task in tasks],
    )


def _schedule(db: Session, server: Server, schedule_id: uuid.UUID) -> Schedule:
    row = db.get(Schedule, schedule_id)
    if row is None or row.server_id != server.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")
    return row


def _audit(db: Session, request: Request, auth: ServerAccess, action: str, name: str) -> None:
    audit.record(
        db,
        f"server.schedule.{action}",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(auth.server.id),
        ip=audit.client_ip(request),
        details={"name": auth.server.name, "schedule": name},
    )


@router.get("/{server_id}/schedules")
def list_schedules(auth: SchedulesView, db: DbSession) -> list[ScheduleOut]:
    rows = db.scalars(
        select(Schedule)
        .where(Schedule.server_id == auth.server.id)
        .order_by(Schedule.created_at, Schedule.name)
    ).all()
    return [_out(db, row) for row in rows]


@router.get("/{server_id}/schedules/{schedule_id}")
def get_schedule(schedule_id: uuid.UUID, auth: SchedulesView, db: DbSession) -> ScheduleOut:
    return _out(db, _schedule(db, auth.server, schedule_id))


@router.post("/{server_id}/schedules", status_code=status.HTTP_201_CREATED)
def create_schedule(
    body: ScheduleCreate, request: Request, auth: SchedulesManage, db: DbSession
) -> ScheduleOut:
    count = db.scalar(
        select(func.count()).select_from(Schedule).where(Schedule.server_id == auth.server.id)
    )
    if (count or 0) >= MAX_SCHEDULES:
        raise HTTPException(status.HTTP_409_CONFLICT, "The schedule limit is reached.")
    expression = build_expression(
        body.minute, body.hour, body.day_of_month, body.month, body.day_of_week
    )
    row = Schedule(
        server_id=auth.server.id,
        name=body.name,
        cron_minute=body.minute.strip(),
        cron_hour=body.hour.strip(),
        cron_day_of_month=body.day_of_month.strip(),
        cron_month=body.month.strip(),
        cron_day_of_week=body.day_of_week.strip(),
        only_when_online=body.only_when_online,
        enabled=body.enabled,
        next_run_at=next_run(expression) if body.enabled else None,
    )
    db.add(row)
    db.commit()
    _audit(db, request, auth, "create", row.name)
    return _out(db, row)


@router.patch("/{server_id}/schedules/{schedule_id}")
def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    request: Request,
    auth: SchedulesManage,
    db: DbSession,
) -> ScheduleOut:
    row = _schedule(db, auth.server, schedule_id)
    changes = body.model_dump(exclude_unset=True)
    values = {field: getattr(row, column) for field, column in CRON_FIELDS.items()}
    for field in CRON_FIELDS:
        if changes.get(field) is not None:
            values[field] = changes[field]
    try:
        expression = build_expression(**values)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    for field, column in CRON_FIELDS.items():
        setattr(row, column, values[field].strip())
    for name in ("name", "only_when_online", "enabled"):
        if changes.get(name) is not None:
            setattr(row, name, changes[name])
    row.next_run_at = next_run(expression) if row.enabled else None
    db.commit()
    _audit(db, request, auth, "update", row.name)
    return _out(db, row)


@router.delete("/{server_id}/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: uuid.UUID, request: Request, auth: SchedulesManage, db: DbSession
) -> Response:
    row = _schedule(db, auth.server, schedule_id)
    name = row.name
    db.delete(row)
    db.commit()
    _audit(db, request, auth, "delete", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{server_id}/schedules/{schedule_id}/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    schedule_id: uuid.UUID,
    body: TaskCreate,
    request: Request,
    auth: SchedulesManage,
    db: DbSession,
) -> ScheduleOut:
    row = _schedule(db, auth.server, schedule_id)
    # Wer keine Power-Aktion, keinen Befehl oder kein Backup auslösen darf, darf auch
    # keinen Zeitplan dafür anlegen.
    if body.action == "power":
        auth.require(POWER_PERMISSION[body.payload])
    elif body.action == "command":
        auth.require(ServerPermission.CONSOLE_COMMAND)
    else:
        auth.require(ServerPermission.BACKUPS_CREATE)
    count, last = db.execute(
        select(func.count(), func.max(ScheduleTask.sequence)).where(
            ScheduleTask.schedule_id == row.id
        )
    ).one()
    if count >= MAX_TASKS:
        raise HTTPException(status.HTTP_409_CONFLICT, "The task limit is reached.")
    db.add(
        ScheduleTask(
            schedule_id=row.id,
            sequence=(last or 0) + 1,
            action=body.action,
            payload=body.payload,
            time_offset=body.time_offset,
            continue_on_failure=body.continue_on_failure,
        )
    )
    db.commit()
    _audit(db, request, auth, "task_add", row.name)
    return _out(db, row)


@router.delete("/{server_id}/schedules/{schedule_id}/tasks/{task_id}")
def delete_task(
    schedule_id: uuid.UUID,
    task_id: uuid.UUID,
    request: Request,
    auth: SchedulesManage,
    db: DbSession,
) -> ScheduleOut:
    row = _schedule(db, auth.server, schedule_id)
    task = db.get(ScheduleTask, task_id)
    if task is None or task.schedule_id != row.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
    db.delete(task)
    db.commit()
    _audit(db, request, auth, "task_delete", row.name)
    return _out(db, row)


@router.post(
    "/{server_id}/schedules/{schedule_id}/execute", status_code=status.HTTP_202_ACCEPTED
)
async def execute_schedule(
    schedule_id: uuid.UUID, auth: SchedulesManage, db: DbSession
) -> dict[str, str]:
    row = _schedule(db, auth.server, schedule_id)
    if schedule_runner.is_running(row.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This schedule is already running.")
    tasks = db.scalar(
        select(func.count()).select_from(ScheduleTask).where(ScheduleTask.schedule_id == row.id)
    )
    if not tasks:
        raise HTTPException(status.HTTP_409_CONFLICT, "This schedule has no tasks.")
    schedule_runner.run_in_background(row.id)
    return {"status": "started"}
