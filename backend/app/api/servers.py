import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agentlink import protocol
from app.agentlink.commands import AgentOffline, broker
from app.agentlink.registry import registry
from app.db import get_db
from app.models import Allocation, Egg, EggVariable, Node, Server, ServerVariable, User
from app.schemas.server import AllocationRef, ServerCreate, ServerOut, ServerUpdate
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit, lifecycle
from app.services import rules as rule_engine
from app.services import startup as startup_service

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
    host_ram = {n.id: getattr(n, "ram_total_mb", None) for n in db.scalars(select(Node))}
    outs = []
    for server in servers:
        out = ServerOut.model_validate(server)
        out.node_name = node_names.get(server.node_id, "")
        out.egg_name = egg_names.get(server.egg_id, "")
        out.allocations = sorted(
            allocations.get(server.id, []), key=lambda a: (not a.is_primary, a.port)
        )
        out.variables = dict(values.get(server.id, {}))
        main = out.allocations[0] if out.allocations else None
        out.startup_command = startup_service.render(
            server.startup,
            out.variables,
            server.memory_mb,
            main.ip if main else None,
            main.port if main else None,
            host_memory_mb=host_ram.get(server.node_id),
        )
        live = registry.server_stats.get(lifecycle.container_name(server.id), {})
        out.live_cpu_percent = live.get("cpu_percent")
        out.live_memory_used_bytes = live.get("memory_used_bytes")
        out.live_disk_used_bytes = live.get("disk_used_bytes")
        out.live_network_rx_bytes = live.get("network_rx_bytes")
        out.live_network_tx_bytes = live.get("network_tx_bytes")
        outs.append(out)
    return outs


def _egg_variables(db: Session, egg_id: uuid.UUID) -> list[EggVariable]:
    return list(db.scalars(select(EggVariable).where(EggVariable.egg_id == egg_id)))


def _check_values(
    variables: list[EggVariable], given: dict[str, str], fill_defaults: bool = False
) -> None:
    """Unbekannte Variablen und Werte, die gegen die Regeln des Eggs verstoßen."""
    by_env = {v.env_variable: v for v in variables}
    unknown = sorted(set(given) - set(by_env))
    if unknown:
        raise HTTPException(422, f"Unknown variables: {', '.join(unknown)}.")
    values = dict(given)
    if fill_defaults:
        for env, variable in by_env.items():
            values.setdefault(env, variable.default_value)
    for env, value in values.items():
        problem = rule_engine.validate(value, by_env[env].rules)
        if problem:
            raise HTTPException(422, f"{by_env[env].name}: {problem}")


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
    _check_values(egg_variables, body.variables, fill_defaults=True)

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
        _check_values(_egg_variables(db, server.egg_id), variables)
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
async def delete_server(
    server_id: uuid.UUID, request: Request, auth: ManageServers, db: DbSession
) -> None:
    server = _get(db, server_id)
    if server.status not in DELETABLE:
        raise _conflict("Stop the server before deleting it.")
    name = server.name
    if server.status != "new":
        await _remove_container(server, skip_offline=True)
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


class PowerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["start", "restart", "stop", "kill"]


# Aus welchem Zustand welche Aktion erlaubt ist, und wohin sie führt.
POWER_FROM = {
    "start": {"offline", "error"},
    "restart": {"running", "starting"},
    "stop": {"running", "starting"},
    "kill": {"running", "starting", "stopping", "error"},
}
POWER_BUSY = {"start": "starting", "restart": "starting", "stop": "stopping", "kill": "stopping"}
# Nach dem Start meldet der Agent selbst "running", sobald der Container wirklich läuft.
POWER_DONE = {"start": None, "restart": None, "stop": "offline", "kill": "offline"}
INSTALL_FROM = {"new", "offline", "error"}


def _set_status(db: Session, server: Server, value: str, error: str | None = None) -> None:
    server.status = value
    server.last_error = error[:1024] if error else None
    db.commit()


async def _send(
    server: Server, action: str, params: dict[str, Any] | None = None
) -> protocol.CommandResult:
    if params is None:
        params = {"name": lifecycle.container_name(server.id)}
    try:
        return await broker.send(server.node_id, action, params)
    except AgentOffline:
        raise _conflict("The node is offline.") from None
    except TimeoutError:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "The node did not answer in time."
        ) from None


async def _agent(server: Server, action: str, params: dict[str, Any] | None = None) -> None:
    result = await _send(server, action, params)
    if not result.ok:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, result.error or "The node reported an error."
        )


async def _remove_container(server: Server, skip_offline: bool = False) -> None:
    """Entfernt den Container. Einen schon fehlenden Container zählt es als Erfolg."""
    try:
        result = await _send(server, "container.remove")
    except HTTPException as exc:
        if skip_offline and exc.status_code == status.HTTP_409_CONFLICT:
            return
        raise
    if not result.ok and "no such" not in (result.error or "").lower():
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, result.error or "The node reported an error."
        )


async def _transition(
    db: Session,
    server: Server,
    busy: str,
    done: str | None,
    work: Callable[[], Awaitable[None]],
) -> None:
    _set_status(db, server, busy)
    try:
        await work()
    except HTTPException as exc:
        _set_status(db, server, "error", str(exc.detail))
        raise
    if done is not None:
        _set_status(db, server, done)


@router.post("/{server_id}/install")
async def install_server(
    server_id: uuid.UUID, request: Request, auth: ManageServers, db: DbSession
) -> ServerOut:
    """Legt Datenverzeichnis und Container an. Das Install-Script läuft noch nicht."""
    server = _get(db, server_id)
    if server.status not in INSTALL_FROM:
        raise _conflict(f"Not possible while the server is {server.status}.")
    out = _outs(db, [server])[0]
    node = db.get(Node, server.node_id)
    egg = db.get(Egg, server.egg_id)
    spec = lifecycle.build_spec(
        server, out.allocations, out.variables, node.ram_total_mb if node else None
    )
    reinstall = server.status != "new"

    async def work() -> None:
        if reinstall:
            await _remove_container(server)
        await _agent(server, "container.create", spec)
        if egg and egg.install_script.strip():
            installer_image, installer_entrypoint = lifecycle.install_settings(egg)
            install_spec = lifecycle.build_install_spec(
                server,
                out.allocations,
                out.variables,
                node.ram_total_mb if node else None,
                egg.install_script,
                installer_image,
                installer_entrypoint,
            )
            await _agent(server, "container.install", install_spec)

    await _transition(db, server, "installing", "offline", work)
    audit.record(
        db,
        "server.install",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, "reinstall": reinstall},
    )
    return _outs(db, [server])[0]


@router.post("/{server_id}/power")
async def power_server(
    server_id: uuid.UUID,
    body: PowerRequest,
    request: Request,
    auth: ManageServers,
    db: DbSession,
) -> ServerOut:
    server = _get(db, server_id)
    if server.status not in POWER_FROM[body.action]:
        raise _conflict(f"Not possible while the server is {server.status}.")

    async def work() -> None:
        if body.action == "restart":
            await _agent(server, "container.stop")
            await _agent(server, "container.start")
        else:
            await _agent(server, f"container.{body.action}")

    await _transition(db, server, POWER_BUSY[body.action], POWER_DONE[body.action], work)
    audit.record(
        db,
        "server.power",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, "action": body.action},
    )
    return _outs(db, [server])[0]


# --- Dateien im Datenverzeichnis des Servers ---------------------------------------------------

# Vorher gibt es kein Datenverzeichnis, oder die Installation schreibt gerade hinein.
FILES_BLOCKED = {"new", "installing"}
# 8 KiB Rohdaten sind als base64 rund 10,9 Tausend Zeichen und bleiben unter dem 16-KiB-Rahmen.
FILE_CHUNK_B64 = 12_000
FILE_MAX_OFFSET = 1 << 30


def _no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Invalid path.")
    return value


FilePath = Annotated[str, Field(max_length=1024), AfterValidator(_no_nul)]


class FileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: FilePath
    offset: int = Field(default=0, ge=0, le=FILE_MAX_OFFSET)
    data: str = Field(max_length=FILE_CHUNK_B64)
    create: bool = True
    truncate: bool = False


class FileFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: FilePath


class FileRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: FilePath
    to: FilePath


class FileDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: FilePath
    recursive: bool = False


# Übersetzt die Fehlertexte des Agents in saubere Statuscodes.
FILE_ERRORS = (
    ("no such file", status.HTTP_404_NOT_FOUND, "File not found."),
    ("file exists", status.HTTP_409_CONFLICT, "A file with this name already exists."),
    ("already exists", status.HTTP_409_CONFLICT, "A file with this name already exists."),
    ("not a directory", status.HTTP_409_CONFLICT, "This is not a directory."),
    ("is a directory", status.HTTP_409_CONFLICT, "This is a directory."),
    ("directory not empty", status.HTTP_409_CONFLICT, "The directory is not empty."),
    ("not a regular file", status.HTTP_409_CONFLICT, "This is not a regular file."),
    ("escapes", status.HTTP_400_BAD_REQUEST, "Invalid path."),
    ("invalid path", status.HTTP_400_BAD_REQUEST, "Invalid path."),
    ("invalid offset", status.HTTP_400_BAD_REQUEST, "Invalid offset."),
    ("invalid data", status.HTTP_400_BAD_REQUEST, "Invalid data."),
    (
        "cannot delete the server root",
        status.HTTP_400_BAD_REQUEST,
        "The server root cannot be deleted.",
    ),
)


def _file_data(result: protocol.CommandResult) -> dict[str, Any]:
    if result.ok:
        return result.data or {}
    message = (result.error or "").lower()
    for needle, code, text in FILE_ERRORS:
        if needle in message:
            raise HTTPException(code, text)
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY, "The node could not complete the file operation."
    )


async def _files(
    db: Session, server_id: uuid.UUID, action: str, **params: Any
) -> tuple[Server, dict[str, Any]]:
    server = _get(db, server_id)
    if server.status in FILES_BLOCKED:
        raise _conflict(f"Files are not available while the server is {server.status}.")
    result = await _send(
        server, action, {"name": lifecycle.container_name(server.id), **params}
    )
    return server, _file_data(result)


def _audit_file(
    db: Session,
    request: Request,
    auth: AuthContext,
    server: Server,
    action: str,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        f"server.file.{action}",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, **details},
    )


@router.get("/{server_id}/files")
async def list_files(
    server_id: uuid.UUID,
    _auth: ManageServers,
    db: DbSession,
    path: Annotated[str, Query(max_length=1024)] = "",
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> dict[str, Any]:
    _, data = await _files(db, server_id, "file.list", path=path, offset=offset)
    return data


@router.get("/{server_id}/files/content")
async def read_file(
    server_id: uuid.UUID,
    _auth: ManageServers,
    db: DbSession,
    path: Annotated[str, Query(max_length=1024)],
    offset: Annotated[int, Query(ge=0, le=FILE_MAX_OFFSET)] = 0,
    length: Annotated[int, Query(ge=1, le=8 * 1024)] = 8 * 1024,
) -> dict[str, Any]:
    _, data = await _files(
        db, server_id, "file.read", path=path, offset=offset, length=length
    )
    return data


@router.put("/{server_id}/files/content", status_code=status.HTTP_204_NO_CONTENT)
async def write_file(
    server_id: uuid.UUID, body: FileWrite, request: Request, auth: ManageServers, db: DbSession
) -> None:
    server, _ = await _files(
        db,
        server_id,
        "file.write",
        path=body.path,
        offset=body.offset,
        data=body.data,
        create=body.create,
        truncate=body.truncate,
    )
    if body.offset == 0:
        _audit_file(db, request, auth, server, "write", {"path": body.path})


@router.post("/{server_id}/files/folder", status_code=status.HTTP_204_NO_CONTENT)
async def create_folder(
    server_id: uuid.UUID, body: FileFolder, request: Request, auth: ManageServers, db: DbSession
) -> None:
    server, _ = await _files(db, server_id, "file.mkdir", path=body.path)
    _audit_file(db, request, auth, server, "mkdir", {"path": body.path})


@router.post("/{server_id}/files/rename", status_code=status.HTTP_204_NO_CONTENT)
async def rename_file(
    server_id: uuid.UUID, body: FileRename, request: Request, auth: ManageServers, db: DbSession
) -> None:
    server, _ = await _files(db, server_id, "file.rename", path=body.path, to=body.to)
    _audit_file(db, request, auth, server, "rename", {"path": body.path, "to": body.to})


@router.post("/{server_id}/files/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    server_id: uuid.UUID, body: FileDelete, request: Request, auth: ManageServers, db: DbSession
) -> None:
    server, _ = await _files(
        db, server_id, "file.delete", path=body.path, recursive=body.recursive
    )
    _audit_file(
        db, request, auth, server, "delete", {"path": body.path, "recursive": body.recursive}
    )


class StartupVariableOut(BaseModel):
    name: str
    env_variable: str
    description: str
    rules: str
    default_value: str
    value: str
    user_editable: bool
    user_viewable: bool


class StartupOut(BaseModel):
    startup: str
    startup_command: str
    egg_startup: str
    image: str
    egg_image: str
    variables: list[StartupVariableOut]


@router.get("/{server_id}/startup")
def get_startup(server_id: uuid.UUID, _auth: ManageServers, db: DbSession) -> StartupOut:
    server = _get(db, server_id)
    out = _outs(db, [server])[0]
    egg = db.get(Egg, server.egg_id)
    variables = [
        StartupVariableOut(
            name=v.name,
            env_variable=v.env_variable,
            description=v.description,
            rules=v.rules,
            default_value=v.default_value,
            value=out.variables.get(v.env_variable, v.default_value),
            user_editable=v.user_editable,
            user_viewable=v.user_viewable,
        )
        for v in sorted(_egg_variables(db, server.egg_id), key=lambda v: v.name.lower())
    ]
    return StartupOut(
        startup=server.startup,
        startup_command=out.startup_command,
        egg_startup=egg.startup if egg else "",
        image=server.image,
        egg_image=egg.docker_image if egg else "",
        variables=variables,
    )
