import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Allocation, Egg, EggVariable, Node, Server, ServerVariable, User
from app.schemas.server import AllocationRef, ServerCreate, ServerOut, ServerUpdate
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit

router = APIRouter(prefix="/servers", tags=["servers"])

ManageServers = Annotated[AuthContext, Depends(require(Permission.PROJECTS_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]

# Nur in diesen Zuständen läuft nichts auf der Node, das beim Löschen übrig bliebe.
DELETABLE = {"new", "offline", "error"}


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _not_found(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


def _get(db: Session, server_id: uuid.UUID) -> Server:
    server = db.get(Server, server_id)
    if server is None:
        raise _not_found("Server not found.")
    return server


def _outs(db: Session, servers: list[Server]) -> list[ServerOut]:
    if not servers:
        return []
    ids = [s.id for s in servers]
    node_names = dict(db.execute(select(Node.id, Node.name)).all())
    egg_names = dict(db.execute(select(Egg.id, Egg.name)).all())
    allocations: dict[uuid.UUID, list[AllocationRef]] = defaultdict(list)
    for a in db.scalars(select(Allocation).where(Allocation.server_id.in_(ids))):
        allocations[a.server_id].append(AllocationRef.model_validate(a))
    values: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    for v in db.scalars(select(ServerVariable).where(ServerVariable.server_id.in_(ids))):
        values[v.server_id][v.env_variable] = v.value
    outs = []
    for server in servers:
        out = ServerOut.model_validate(server)
        out.node_name = node_names.get(server.node_id, "")
        out.egg_name = egg_names.get(server.egg_id, "")
        out.allocations = sorted(
            allocations.get(server.id, []), key=lambda a: (not a.is_primary, a.port)
        )
        out.variables = dict(values.get(server.id, {}))
        outs.append(out)
    return outs


def _unknown_variables(db: Session, egg_id: uuid.UUID, given: dict[str, str]) -> None:
    known = set(db.scalars(select(EggVariable.env_variable).where(EggVariable.egg_id == egg_id)))
    unknown = sorted(set(given) - known)
    if unknown:
        raise HTTPException(422, f"Unknown variables: {', '.join(unknown)}.")


@router.get("")
def list_servers(_auth: ManageServers, db: DbSession) -> list[ServerOut]:
    return _outs(db, list(db.scalars(select(Server).order_by(Server.created_at))))


@router.get("/{server_id}")
def get_server(server_id: uuid.UUID, _auth: ManageServers, db: DbSession) -> ServerOut:
    return _outs(db, [_get(db, server_id)])[0]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_server(
    body: ServerCreate, request: Request, auth: ManageServers, db: DbSession
) -> ServerOut:
    if db.get(User, body.owner_id) is None:
        raise _not_found("User not found.")
    node = db.get(Node, body.node_id)
    if node is None:
        raise _not_found("Node not found.")
    egg = db.get(Egg, body.egg_id)
    if egg is None:
        raise _not_found("Egg not found.")
    egg_variables = list(db.scalars(select(EggVariable).where(EggVariable.egg_id == egg.id)))
    _unknown_variables(db, egg.id, body.variables)

    wanted = [body.allocation_id, *body.extra_allocation_ids]
    found = {a.id: a for a in db.scalars(select(Allocation).where(Allocation.id.in_(wanted)))}
    for allocation_id in wanted:
        allocation = found.get(allocation_id)
        if allocation is None or allocation.node_id != node.id:
            raise HTTPException(422, "An allocation does not exist on this node.")
        if allocation.server_id is not None:
            raise _conflict("An allocation is already in use.")

    server = Server(
        name=body.name,
        description=body.description,
        owner_id=body.owner_id,
        node_id=node.id,
        egg_id=egg.id,
        image=body.image or egg.docker_image,
        startup=body.startup if body.startup is not None else egg.startup,
        memory_mb=body.memory_mb,
        cpus=body.cpus,
        disk_mb=body.disk_mb,
        status="new",
    )
    db.add(server)
    db.flush()
    for index, allocation_id in enumerate(wanted):
        # Bedingtes Update, damit zwei gleichzeitige Anfragen nicht dieselbe Allocation belegen.
        claimed = db.execute(
            update(Allocation)
            .where(Allocation.id == allocation_id, Allocation.server_id.is_(None))
            .values(server_id=server.id, is_primary=index == 0)
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise _conflict("An allocation is already in use.")
    for variable in egg_variables:
        value = body.variables.get(variable.env_variable, variable.default_value)
        db.add(ServerVariable(server_id=server.id, env_variable=variable.env_variable, value=value))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("An allocation is already in use.") from None
    db.expire_all()
    # Variablen stehen nicht im Audit-Log, sie können Secrets enthalten.
    audit.record(
        db,
        "server.create",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, "node": node.name, "egg": egg.name},
    )
    return _outs(db, [server])[0]


@router.patch("/{server_id}")
def update_server(
    server_id: uuid.UUID,
    body: ServerUpdate,
    request: Request,
    auth: ManageServers,
    db: DbSession,
) -> ServerOut:
    server = _get(db, server_id)
    data = body.model_dump(exclude_unset=True)
    variables = data.pop("variables", None)
    if variables is not None:
        _unknown_variables(db, server.egg_id, variables)
        rows = {
            v.env_variable: v
            for v in db.scalars(
                select(ServerVariable).where(ServerVariable.server_id == server.id)
            )
        }
        for key, value in variables.items():
            if key in rows:
                rows[key].value = value
            else:
                db.add(ServerVariable(server_id=server.id, env_variable=key, value=value))
    for field, value in data.items():
        setattr(server, field, value)
    db.commit()
    audit.record(
        db,
        "server.update",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, "fields": sorted(body.model_fields_set)},
    )
    return _outs(db, [server])[0]


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: uuid.UUID, request: Request, auth: ManageServers, db: DbSession
) -> None:
    server = _get(db, server_id)
    if server.status not in DELETABLE:
        raise _conflict("Stop the server before deleting it.")
    name = server.name
    db.execute(
        update(Allocation)
        .where(Allocation.server_id == server.id)
        .values(server_id=None, is_primary=False)
    )
    db.delete(server)
    db.commit()
    db.expire_all()
    audit.record(
        db,
        "server.delete",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server_id),
        ip=audit.client_ip(request),
        details={"name": name},
    )
