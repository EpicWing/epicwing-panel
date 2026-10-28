import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Egg, EggVariable, Nest, Server
from app.schemas.egg import (
    EggCreate,
    EggOut,
    EggUpdate,
    EggVariableIn,
    EggVariableOut,
    NestCreate,
    NestOut,
    NestUpdate,
)
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit

nests_router = APIRouter(prefix="/nests", tags=["nests"])
router = APIRouter(prefix="/eggs", tags=["eggs"])

ManageNodes = Annotated[AuthContext, Depends(require(Permission.NODES_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _not_found(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


# --- Nests ---


def _nest_out(nest: Nest, egg_count: int) -> NestOut:
    out = NestOut.model_validate(nest)
    out.egg_count = egg_count
    return out


def _get_nest(db: Session, nest_id: uuid.UUID) -> Nest:
    nest = db.get(Nest, nest_id)
    if nest is None:
        raise _not_found("Nest not found.")
    return nest


def _nest_name_taken(db: Session, name: str, exclude: uuid.UUID | None = None) -> bool:
    query = select(Nest.id).where(func.lower(Nest.name) == name.lower())
    if exclude is not None:
        query = query.where(Nest.id != exclude)
    return db.scalar(query) is not None


def _egg_count(db: Session, nest_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Egg).where(Egg.nest_id == nest_id)) or 0


@nests_router.get("")
def list_nests(_auth: ManageNodes, db: DbSession) -> list[NestOut]:
    counts = dict(db.execute(select(Egg.nest_id, func.count()).group_by(Egg.nest_id)).all())
    nests = db.scalars(select(Nest).order_by(Nest.name))
    return [_nest_out(n, counts.get(n.id, 0)) for n in nests]


@nests_router.post("", status_code=status.HTTP_201_CREATED)
def create_nest(
    body: NestCreate, request: Request, auth: ManageNodes, db: DbSession
) -> NestOut:
    if _nest_name_taken(db, body.name):
        raise _conflict("A nest with this name already exists.")
    nest = Nest(name=body.name, description=body.description)
    db.add(nest)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("A nest with this name already exists.") from None
    audit.record(
        db,
        "nest.create",
        actor_id=auth.user.id,
        target_type="nest",
        target_id=str(nest.id),
        ip=audit.client_ip(request),
        details={"name": nest.name},
    )
    return _nest_out(nest, 0)


@nests_router.patch("/{nest_id}")
def update_nest(
    nest_id: uuid.UUID, body: NestUpdate, request: Request, auth: ManageNodes, db: DbSession
) -> NestOut:
    nest = _get_nest(db, nest_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and _nest_name_taken(db, data["name"], nest.id):
        raise _conflict("A nest with this name already exists.")
    for field, value in data.items():
        setattr(nest, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("A nest with this name already exists.") from None
    audit.record(
        db,
        "nest.update",
        actor_id=auth.user.id,
        target_type="nest",
        target_id=str(nest.id),
        ip=audit.client_ip(request),
        details={"name": nest.name, "fields": sorted(data)},
    )
    return _nest_out(nest, _egg_count(db, nest.id))


@nests_router.delete("/{nest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_nest(nest_id: uuid.UUID, request: Request, auth: ManageNodes, db: DbSession) -> None:
    nest = _get_nest(db, nest_id)
    if _egg_count(db, nest.id) > 0:
        raise _conflict("This nest still contains eggs. Delete them first.")
    name = nest.name
    db.delete(nest)
    db.commit()
    audit.record(
        db,
        "nest.delete",
        actor_id=auth.user.id,
        target_type="nest",
        target_id=str(nest_id),
        ip=audit.client_ip(request),
        details={"name": name},
    )


# --- Eggs ---


def _get_egg(db: Session, egg_id: uuid.UUID) -> Egg:
    egg = db.get(Egg, egg_id)
    if egg is None:
        raise _not_found("Egg not found.")
    return egg


def _egg_outs(db: Session, eggs: list[Egg]) -> list[EggOut]:
    if not eggs:
        return []
    nest_names = dict(db.execute(select(Nest.id, Nest.name)).all())
    grouped: dict[uuid.UUID, list[EggVariable]] = defaultdict(list)
    rows = db.scalars(
        select(EggVariable)
        .where(EggVariable.egg_id.in_([e.id for e in eggs]))
        .order_by(EggVariable.name)
    )
    for row in rows:
        grouped[row.egg_id].append(row)
    outs = []
    for egg in eggs:
        out = EggOut.model_validate(egg)
        out.nest_name = nest_names.get(egg.nest_id, "")
        out.variables = [EggVariableOut.model_validate(v) for v in grouped.get(egg.id, [])]
        outs.append(out)
    return outs


def _variable_rows(egg_id: uuid.UUID, variables: list[EggVariableIn]) -> list[EggVariable]:
    return [
        EggVariable(
            egg_id=egg_id,
            name=v.name,
            env_variable=v.env_variable,
            default_value=v.default_value,
            description=v.description,
            user_editable=v.user_editable,
        )
        for v in variables
    ]


def _check_free_name(
    db: Session, nest_id: uuid.UUID, name: str, exclude: uuid.UUID | None
) -> None:
    query = select(Egg.id).where(Egg.nest_id == nest_id, func.lower(Egg.name) == name.lower())
    if exclude is not None:
        query = query.where(Egg.id != exclude)
    if db.scalar(query) is not None:
        raise _conflict("An egg with this name already exists in this nest.")


@router.get("")
def list_eggs(
    _auth: ManageNodes, db: DbSession, nest_id: uuid.UUID | None = None
) -> list[EggOut]:
    query = select(Egg).order_by(Egg.name)
    if nest_id is not None:
        query = query.where(Egg.nest_id == nest_id)
    return _egg_outs(db, list(db.scalars(query)))


@router.get("/{egg_id}")
def get_egg(egg_id: uuid.UUID, _auth: ManageNodes, db: DbSession) -> EggOut:
    return _egg_outs(db, [_get_egg(db, egg_id)])[0]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_egg(body: EggCreate, request: Request, auth: ManageNodes, db: DbSession) -> EggOut:
    nest = _get_nest(db, body.nest_id)
    _check_free_name(db, nest.id, body.name, None)
    egg = Egg(
        nest_id=nest.id,
        name=body.name,
        description=body.description,
        docker_image=body.docker_image,
        startup=body.startup,
        stop_command=body.stop_command,
        install_script=body.install_script,
    )
    db.add(egg)
    try:
        db.flush()
        db.add_all(_variable_rows(egg.id, body.variables))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("An egg with this name already exists in this nest.") from None
    audit.record(
        db,
        "egg.create",
        actor_id=auth.user.id,
        target_type="egg",
        target_id=str(egg.id),
        ip=audit.client_ip(request),
        details={"name": egg.name, "nest": nest.name},
    )
    return _egg_outs(db, [egg])[0]


@router.patch("/{egg_id}")
def update_egg(
    egg_id: uuid.UUID, body: EggUpdate, request: Request, auth: ManageNodes, db: DbSession
) -> EggOut:
    egg = _get_egg(db, egg_id)
    data = body.model_dump(exclude_unset=True, exclude={"variables"})
    if "nest_id" in data:
        _get_nest(db, data["nest_id"])
    _check_free_name(db, data.get("nest_id", egg.nest_id), data.get("name", egg.name), egg.id)
    for field, value in data.items():
        setattr(egg, field, value)
    if body.variables is not None:
        db.execute(delete(EggVariable).where(EggVariable.egg_id == egg.id))
        db.add_all(_variable_rows(egg.id, body.variables))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("An egg with this name already exists in this nest.") from None
    audit.record(
        db,
        "egg.update",
        actor_id=auth.user.id,
        target_type="egg",
        target_id=str(egg.id),
        ip=audit.client_ip(request),
        details={"name": egg.name, "fields": sorted(body.model_fields_set)},
    )
    return _egg_outs(db, [egg])[0]


@router.delete("/{egg_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_egg(egg_id: uuid.UUID, request: Request, auth: ManageNodes, db: DbSession) -> None:
    egg = _get_egg(db, egg_id)
    used = db.scalar(select(func.count()).select_from(Server).where(Server.egg_id == egg.id))
    if used:
        raise _conflict("Servers still use this egg.")
    name = egg.name
    db.delete(egg)
    db.commit()
    audit.record(
        db,
        "egg.delete",
        actor_id=auth.user.id,
        target_type="egg",
        target_id=str(egg_id),
        ip=audit.client_ip(request),
        details={"name": name},
    )
