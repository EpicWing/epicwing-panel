import asyncio
import base64
import contextlib
import re
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
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
from app.security.server_access import (
    ServerAccess,
    ServerPermission,
    effective_permissions,
    is_server_admin,
    server_access,
    visible_servers,
)
from app.security.sessions import AuthContext, CurrentAuth
from app.services import audit, lifecycle, server_databases, transfer
from app.services import rules as rule_engine
from app.services import startup as startup_service

router = APIRouter(prefix="/servers", tags=["servers"])

ManageServers = Annotated[AuthContext, Depends(require(Permission.PROJECTS_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]
ServerView = Annotated[ServerAccess, Depends(server_access(ServerPermission.VIEW))]
ServerReinstall = Annotated[
    ServerAccess, Depends(server_access(ServerPermission.SETTINGS_REINSTALL))
]
FilesRead = Annotated[ServerAccess, Depends(server_access(ServerPermission.FILES_READ))]
FilesWrite = Annotated[ServerAccess, Depends(server_access(ServerPermission.FILES_WRITE))]
StartupView = Annotated[ServerAccess, Depends(server_access(ServerPermission.STARTUP_VIEW))]

# Nur in diesen Zuständen läuft nichts auf der Node, das beim Löschen übrig bliebe.
DELETABLE = {"new", "offline", "error"}


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _not_found(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


class NodeOffline(HTTPException):
    """Die Node hat keine Verbindung. Auf der Node wurde nichts ausgeführt."""

    def __init__(self) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "The node is offline.")


# Pro Server läuft immer nur eine Aktion. Gilt für einen Prozess; bei mehreren Workern
# braucht es später eine Sperre in der Datenbank.
_locks: dict[uuid.UUID, asyncio.Lock] = {}


@contextlib.asynccontextmanager
async def _exclusive(server_id: uuid.UUID) -> AsyncIterator[None]:
    lock = _locks.setdefault(server_id, asyncio.Lock())
    if lock.locked():
        raise _conflict("Another action is already running for this server.")
    try:
        async with lock:
            yield
    finally:
        _locks.pop(server_id, None)


def _get(db: Session, server_id: uuid.UUID) -> Server:
    server = db.get(Server, server_id)
    if server is None:
        raise _not_found("Server not found.")
    return server


def _outs(
    db: Session, servers: list[Server], viewer: User | None = None
) -> list[ServerOut]:
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
    # Mit viewer werden die eigenen Rechte eingetragen. Für Nicht-Admins fehlen dann die
    # Variablen, die der Egg-Autor als nicht sichtbar markiert hat.
    permissions: dict[uuid.UUID, set[str]] = {}
    hidden: set[tuple[uuid.UUID, str]] = set()
    if viewer is not None:
        permissions = effective_permissions(db, viewer, servers)
        if not is_server_admin(db, viewer):
            hidden = {
                (v.egg_id, v.env_variable)
                for v in db.scalars(
                    select(EggVariable).where(EggVariable.user_viewable.is_(False))
                )
            }
    outs = []
    for server in servers:
        out = ServerOut.model_validate(server)
        out.node_name = node_names.get(server.node_id, "")
        out.egg_name = egg_names.get(server.egg_id, "")
        out.allocations = sorted(
            allocations.get(server.id, []), key=lambda a: (not a.is_primary, a.port)
        )
        out.variables = {
            key: value
            for key, value in values.get(server.id, {}).items()
            if (server.egg_id, key) not in hidden
        }
        out.permissions = sorted(permissions.get(server.id, ()))
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
def list_servers(auth: CurrentAuth, db: DbSession) -> list[ServerOut]:
    servers = db.scalars(visible_servers(db, auth.user).order_by(Server.created_at))
    return _outs(db, list(servers), auth.user)


@router.get("/{server_id}")
def get_server(server_id: uuid.UUID, auth: ServerView, db: DbSession) -> ServerOut:
    return _outs(db, [_get(db, server_id)], auth.user)[0]


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
    return _outs(db, [server], auth.user)[0]


# Wer darf welches Feld ändern? Felder ohne Eintrag (Image, Startbefehl, Ressourcen) darf
# nur ein Administrator ändern, denn sie bestimmen, was auf der Node läuft.
UPDATE_RIGHTS = {
    "name": ServerPermission.SETTINGS_UPDATE,
    "description": ServerPermission.SETTINGS_UPDATE,
    "variables": ServerPermission.STARTUP_UPDATE,
}


def _check_update_rights(auth: ServerAccess, fields: set[str]) -> None:
    for field in sorted(fields):
        right = UPDATE_RIGHTS.get(field)
        if right is not None:
            auth.require(right)
        elif not auth.is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Only administrators can change {field}."
            )


@router.patch("/{server_id}")
def update_server(
    server_id: uuid.UUID,
    body: ServerUpdate,
    request: Request,
    auth: ServerView,
    db: DbSession,
) -> ServerOut:
    server = _get(db, server_id)
    data = body.model_dump(exclude_unset=True)
    _check_update_rights(auth, set(data))
    variables = data.pop("variables", None)
    if variables is not None:
        _check_values(_egg_variables(db, server.egg_id), variables)
        rows = {
            v.env_variable: v
            for v in db.scalars(
                select(ServerVariable).where(ServerVariable.server_id == server.id)
            )
        }
        if not auth.is_admin:
            # Gesperrte und nicht sichtbare Variablen dürfen nur Administratoren ändern.
            locked = {
                v.env_variable: v
                for v in _egg_variables(db, server.egg_id)
                if not v.user_editable or not v.user_viewable
            }
            changed = sorted(
                key
                for key, value in variables.items()
                if key in locked
                and value != (rows[key].value if key in rows else locked[key].default_value)
            )
            if changed:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"These variables are locked: {', '.join(changed)}.",
                )
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
    return _outs(db, [server], auth.user)[0]


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
    await server_databases.drop_all(db, server.id)
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
POWER_BUSY = {"start": "starting", "restart": "stopping", "stop": "stopping", "kill": "stopping"}
# Nach dem Start meldet der Agent selbst "running", sobald der Container wirklich läuft.
POWER_DONE = {"start": None, "restart": None, "stop": "offline", "kill": "offline"}
INSTALL_FROM = {"new", "offline", "error"}
POWER_PERMISSION = {
    "start": ServerPermission.POWER_START,
    "restart": ServerPermission.POWER_RESTART,
    "stop": ServerPermission.POWER_STOP,
    "kill": ServerPermission.POWER_STOP,
}


def _set_status(db: Session, server: Server, value: str, error: str | None = None) -> None:
    server.status = value
    server.last_error = error[:1024] if error else None
    db.commit()


async def _send(
    server: Server,
    action: str,
    params: dict[str, Any] | None = None,
    timeout: float = protocol.COMMAND_TIMEOUT_SECONDS,
) -> protocol.CommandResult:
    if params is None:
        params = {"name": lifecycle.container_name(server.id)}
    try:
        return await broker.send(server.node_id, action, params, timeout)
    except AgentOffline:
        raise NodeOffline() from None
    except TimeoutError:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "The node did not answer in time."
        ) from None


async def _agent(
    server: Server,
    action: str,
    params: dict[str, Any] | None = None,
    timeout: float = protocol.COMMAND_TIMEOUT_SECONDS,
) -> None:
    result = await _send(server, action, params, timeout)
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
    keep_on_offline: bool = False,
    timeout_status: str | None = None,
) -> None:
    previous, previous_error = server.status, server.last_error
    _set_status(db, server, busy)
    try:
        await work()
    except HTTPException as exc:
        if keep_on_offline and isinstance(exc, NodeOffline):
            # Die Node war nicht erreichbar, der Zustand des Servers ist unverändert. Nach dem
            # Verbindungsaufbau meldet der Agent den echten Zustand ohnehin.
            _set_status(db, server, previous, previous_error)
        elif timeout_status is not None and exc.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
            # Ein laufender Vorgang (z. B. installation) läuft auf der Node möglicherweise weiter.
            _set_status(db, server, timeout_status)
        else:
            _set_status(db, server, "error", str(exc.detail))
        raise
    if done is not None:
        _set_status(db, server, done)


@router.post("/{server_id}/install")
async def install_server(
    server_id: uuid.UUID, request: Request, auth: ServerReinstall, db: DbSession
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
            await _agent(
                server,
                "container.install",
                install_spec,
                timeout=protocol.INSTALL_COMMAND_TIMEOUT_SECONDS,
            )

    await _transition(db, server, "installing", "offline", work, timeout_status="installing")
    audit.record(
        db,
        "server.install",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, "reinstall": reinstall},
    )
    return _outs(db, [server], auth.user)[0]


async def perform_power(db: Session, server: Server, action: str) -> None:
    """Führt eine Power-Aktion aus. Endpunkt und Zeitpläne nutzen dieselbe Logik."""
    # Kill ist der Notausgang und darf auch laufen, während ein Stop noch wartet.
    guard = contextlib.nullcontext() if action == "kill" else _exclusive(server.id)
    async with guard:
        db.refresh(server)
        if server.status not in POWER_FROM[action]:
            raise _conflict(f"Not possible while the server is {server.status}.")

        # Mit stop_command im Egg stoppt der Agent über die Konsole und fällt sonst auf
        # docker stop zurück. Pterodactyl-Signale (^C) stehen leer in der DB.
        stop_params = None
        if action in ("stop", "restart"):
            egg = db.get(Egg, server.egg_id)
            command = (egg.stop_command or "").strip() if egg else ""
            if command:
                stop_params = {
                    "name": lifecycle.container_name(server.id),
                    "command": command,
                }

        async def work() -> None:
            if action == "restart":
                await _agent(server, "container.stop", stop_params)
                _set_status(db, server, "starting")
                await _agent(server, "container.start")
            elif action == "stop":
                await _agent(server, "container.stop", stop_params)
            else:
                await _agent(server, f"container.{action}")

        await _transition(
            db,
            server,
            POWER_BUSY[action],
            POWER_DONE[action],
            work,
            keep_on_offline=True,
        )


@router.post("/{server_id}/power")
async def power_server(
    server_id: uuid.UUID,
    body: PowerRequest,
    request: Request,
    auth: ServerView,
    db: DbSession,
) -> ServerOut:
    server = _get(db, server_id)
    auth.require(POWER_PERMISSION[body.action])
    await perform_power(db, server, body.action)
    audit.record(
        db,
        "server.power",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": server.name, "action": body.action},
    )
    return _outs(db, [server], auth.user)[0]


# --- Dateien im Datenverzeichnis des Servers ---------------------------------------------------

# Vorher gibt es kein Datenverzeichnis, oder die Installation schreibt gerade hinein.
FILES_BLOCKED = {"new", "installing"}
# 8 KiB Rohdaten sind als base64 rund 10,9 Tausend Zeichen und bleiben unter dem 16-KiB-Rahmen.
FILE_CHUNK_B64 = 12_000
FILE_MAX_OFFSET = 1 << 30
FILE_READ_CHUNK = 8 * 1024
FILE_DOWNLOAD_WINDOW = 3  # Stücke, die gleichzeitig beim Agent angefragt sind
FILE_DOWNLOAD_RETRIES = 4
# Ein großes Archiv braucht länger als ein normaler Dateibefehl.
DECOMPRESS_TIMEOUT_SECONDS = 600


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


class FileDecompress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: FilePath
    # Leer heißt: der Ordner, in dem das Archiv liegt.
    to: FilePath = ""


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
    ("unsafe path in archive", 400, "The archive contains unsafe paths and was not unpacked."),
    ("archive limit exceeded", 413, "The archive is too large or has too many files."),
    ("invalid archive", 422, "The archive is damaged or not a valid archive."),
    ("unsupported archive type", 400, "Only .zip, .tar.gz and .tgz archives can be unpacked."),
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
    _auth: FilesRead,
    db: DbSession,
    path: Annotated[str, Query(max_length=1024)] = "",
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> dict[str, Any]:
    _, data = await _files(db, server_id, "file.list", path=path, offset=offset)
    return data


@router.get("/{server_id}/files/content")
async def read_file(
    server_id: uuid.UUID,
    _auth: FilesRead,
    db: DbSession,
    path: Annotated[str, Query(max_length=1024)],
    offset: Annotated[int, Query(ge=0, le=FILE_MAX_OFFSET)] = 0,
    length: Annotated[int, Query(ge=1, le=8 * 1024)] = 8 * 1024,
) -> dict[str, Any]:
    _, data = await _files(
        db, server_id, "file.read", path=path, offset=offset, length=length
    )
    return data


def _attachment(name: str) -> str:
    plain = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "download"
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


def _decode_chunk(data: dict[str, Any]) -> bytes:
    return base64.b64decode(str(data.get("data", "")), validate=True)


@router.get("/{server_id}/files/download")
async def download_file(
    server_id: uuid.UUID,
    request: Request,
    auth: FilesRead,
    db: DbSession,
    path: Annotated[str, Query(min_length=1, max_length=1024)],
) -> StreamingResponse:
    server, first = await _files(
        db, server_id, "file.read", path=path, offset=0, length=FILE_READ_CHUNK
    )
    size = first.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The node sent an invalid size.")
    try:
        head = _decode_chunk(first)
    except ValueError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The node sent an invalid chunk."
        ) from None
    if len(head) != min(FILE_READ_CHUNK, size):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The node sent an incomplete chunk.")
    # Ab hier nur noch einfache Werte: der Stream darf die Datenbank nicht mehr anfassen.
    node_id = server.node_id
    params = {"name": lifecycle.container_name(server.id), "path": path}
    filename = path.rstrip("/").rsplit("/", 1)[-1]
    _audit_file(db, request, auth, server, "download", {"path": path})
    db.commit()

    async def fetch(offset: int) -> bytes:
        for attempt in range(1, FILE_DOWNLOAD_RETRIES + 1):
            try:
                result = await broker.send(
                    node_id, "file.read", {**params, "offset": offset, "length": FILE_READ_CHUNK}
                )
            except (AgentOffline, TimeoutError):
                raise transfer.TransferError("The node is not reachable.") from None
            busy = "too many open commands" in (result.error or "").lower()
            if result.ok or not busy:
                break
            await asyncio.sleep(0.2 * attempt)
        if not result.ok:
            raise transfer.TransferError(result.error or "The node could not read the file.")
        try:
            return _decode_chunk(result.data or {})
        except ValueError:
            raise transfer.TransferError("The node sent an invalid chunk.") from None

    return StreamingResponse(
        transfer.stream(fetch, head, size, FILE_READ_CHUNK, FILE_DOWNLOAD_WINDOW),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": _attachment(filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.put("/{server_id}/files/content", status_code=status.HTTP_204_NO_CONTENT)
async def write_file(
    server_id: uuid.UUID, body: FileWrite, request: Request, auth: FilesWrite, db: DbSession
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
    server_id: uuid.UUID, body: FileFolder, request: Request, auth: FilesWrite, db: DbSession
) -> None:
    server, _ = await _files(db, server_id, "file.mkdir", path=body.path)
    _audit_file(db, request, auth, server, "mkdir", {"path": body.path})


@router.post("/{server_id}/files/rename", status_code=status.HTTP_204_NO_CONTENT)
async def rename_file(
    server_id: uuid.UUID, body: FileRename, request: Request, auth: FilesWrite, db: DbSession
) -> None:
    server, _ = await _files(db, server_id, "file.rename", path=body.path, to=body.to)
    _audit_file(db, request, auth, server, "rename", {"path": body.path, "to": body.to})


@router.post("/{server_id}/files/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    server_id: uuid.UUID, body: FileDelete, request: Request, auth: FilesWrite, db: DbSession
) -> None:
    server, _ = await _files(
        db, server_id, "file.delete", path=body.path, recursive=body.recursive
    )
    _audit_file(
        db, request, auth, server, "delete", {"path": body.path, "recursive": body.recursive}
    )


@router.post("/{server_id}/files/decompress")
async def decompress_file(
    server_id: uuid.UUID, body: FileDecompress, request: Request, auth: FilesWrite, db: DbSession
) -> dict[str, Any]:
    server = _get(db, server_id)
    if server.status in FILES_BLOCKED:
        raise _conflict(f"Files are not available while the server is {server.status}.")
    result = await _send(
        server,
        "file.decompress",
        {"name": lifecycle.container_name(server.id), "path": body.path, "to": body.to},
        timeout=DECOMPRESS_TIMEOUT_SECONDS,
    )
    data = _file_data(result)
    _audit_file(
        db,
        request,
        auth,
        server,
        "decompress",
        {"path": body.path, "to": body.to, "files": data.get("files", 0)},
    )
    return data


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
def get_startup(server_id: uuid.UUID, auth: StartupView, db: DbSession) -> StartupOut:
    server = _get(db, server_id)
    out = _outs(db, [server], auth.user)[0]
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
        if auth.is_admin or v.user_viewable
    ]
    return StartupOut(
        startup=server.startup,
        startup_command=out.startup_command,
        egg_startup=egg.startup if egg else "",
        image=server.image,
        egg_image=egg.docker_image if egg else "",
        variables=variables,
    )


# --- Allocations eines Servers ------------------------------------------------------------------

# Der Agent veröffentlicht höchstens 32 Ports, jede Allocation belegt TCP und UDP.
MAX_ALLOCATIONS = 16
# Nur hier läuft nichts im Container. Die neuen Ports gelten durch ein neues Erzeugen.
ALLOCATIONS_EDIT_FROM = {"new", "offline", "error"}

AllocationsView = Annotated[
    ServerAccess, Depends(server_access(ServerPermission.ALLOCATIONS_VIEW))
]
AllocationsManage = Annotated[
    ServerAccess, Depends(server_access(ServerPermission.ALLOCATIONS_MANAGE))
]


class AllocationAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocation_id: uuid.UUID


def _server_allocations(db: Session, server_id: uuid.UUID) -> list[Allocation]:
    rows = db.scalars(select(Allocation).where(Allocation.server_id == server_id))
    return sorted(rows, key=lambda a: (not a.is_primary, a.port, a.ip))


def _spec_for(db: Session, server: Server) -> dict[str, Any]:
    out = _outs(db, [server])[0]
    node = db.get(Node, server.node_id)
    return lifecycle.build_spec(
        server, out.allocations, out.variables, node.ram_total_mb if node else None
    )


async def _change_allocations(
    db: Session, server: Server, mutate: Callable[[], bool]
) -> None:
    """Ändert die Allocations und erzeugt den Container mit den neuen Ports neu.

    Das Datenverzeichnis bleibt, das Install-Script läuft nicht. Scheitert etwas, bleibt die
    Datenbank unverändert und der alte Container wird wiederhergestellt. mutate gibt zurück,
    ob sich etwas geändert hat."""
    async with _exclusive(server.id):
        db.refresh(server)
        if server.status not in ALLOCATIONS_EDIT_FROM:
            raise _conflict(f"Not possible while the server is {server.status}.")
        has_container = server.status != "new"
        old_spec = _spec_for(db, server) if has_container else None
        try:
            changed = mutate()
        except HTTPException:
            db.rollback()
            raise
        if not changed:
            return
        if has_container:
            db.expire_all()
            new_spec = _spec_for(db, server)
            removed = False
            try:
                await _remove_container(server)
                removed = True
                await _agent(server, "container.create", new_spec)
            except HTTPException:
                db.rollback()
                if removed:
                    try:
                        await _agent(server, "container.create", old_spec)
                    except HTTPException:
                        _set_status(
                            db, server, "error", "The container is missing. Reinstall the server."
                        )
                raise
        db.commit()


def _audit_allocation(
    db: Session, request: Request, auth: ServerAccess, action: str, details: dict[str, Any]
) -> None:
    audit.record(
        db,
        f"server.allocation.{action}",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(auth.server.id),
        ip=audit.client_ip(request),
        details={"name": auth.server.name, **details},
    )


@router.get("/{server_id}/allocations")
def list_server_allocations(auth: AllocationsView, db: DbSession) -> list[AllocationRef]:
    return [AllocationRef.model_validate(a) for a in _server_allocations(db, auth.server.id)]


@router.get("/{server_id}/allocations/free")
def list_free_allocations(auth: AllocationsManage, db: DbSession) -> list[AllocationRef]:
    rows = db.scalars(
        select(Allocation)
        .where(Allocation.node_id == auth.server.node_id, Allocation.server_id.is_(None))
        .order_by(Allocation.port, Allocation.ip)
        .limit(200)
    )
    return [AllocationRef.model_validate(a) for a in rows]


@router.post("/{server_id}/allocations", status_code=status.HTTP_201_CREATED)
async def add_allocation(
    body: AllocationAdd, request: Request, auth: AllocationsManage, db: DbSession
) -> list[AllocationRef]:
    server = auth.server

    def mutate() -> bool:
        if len(_server_allocations(db, server.id)) >= MAX_ALLOCATIONS:
            raise _conflict(f"A server can have at most {MAX_ALLOCATIONS} allocations.")
        allocation = db.get(Allocation, body.allocation_id)
        if allocation is None or allocation.node_id != server.node_id:
            raise HTTPException(422, "The allocation does not exist on this node.")
        # Bedingtes Update, damit zwei gleichzeitige Anfragen nicht dieselbe Allocation belegen.
        claimed = db.execute(
            update(Allocation)
            .where(Allocation.id == allocation.id, Allocation.server_id.is_(None))
            .values(server_id=server.id, is_primary=False)
        )
        if claimed.rowcount != 1:
            raise _conflict("The allocation is already in use.")
        return True

    await _change_allocations(db, server, mutate)
    _audit_allocation(db, request, auth, "add", {"allocation": str(body.allocation_id)})
    return [AllocationRef.model_validate(a) for a in _server_allocations(db, server.id)]


@router.delete("/{server_id}/allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_allocation(
    allocation_id: uuid.UUID, request: Request, auth: AllocationsManage, db: DbSession
) -> None:
    server = auth.server
    details: dict[str, Any] = {}

    def mutate() -> bool:
        allocation = db.get(Allocation, allocation_id)
        if allocation is None or allocation.server_id != server.id:
            raise _not_found("Allocation not found.")
        if allocation.is_primary:
            raise _conflict("The primary allocation cannot be removed. Make another one primary.")
        details.update(ip=allocation.ip, port=allocation.port)
        db.execute(
            update(Allocation)
            .where(Allocation.id == allocation.id, Allocation.server_id == server.id)
            .values(server_id=None, is_primary=False)
        )
        return True

    await _change_allocations(db, server, mutate)
    _audit_allocation(db, request, auth, "remove", details)


@router.put("/{server_id}/allocations/{allocation_id}/primary")
async def set_primary_allocation(
    allocation_id: uuid.UUID, request: Request, auth: AllocationsManage, db: DbSession
) -> list[AllocationRef]:
    server = auth.server
    details: dict[str, Any] = {}

    def mutate() -> bool:
        allocation = db.get(Allocation, allocation_id)
        if allocation is None or allocation.server_id != server.id:
            raise _not_found("Allocation not found.")
        if allocation.is_primary:
            return False
        details.update(ip=allocation.ip, port=allocation.port)
        db.execute(
            update(Allocation).where(Allocation.server_id == server.id).values(is_primary=False)
        )
        db.execute(update(Allocation).where(Allocation.id == allocation.id).values(is_primary=True))
        return True

    await _change_allocations(db, server, mutate)
    if details:
        _audit_allocation(db, request, auth, "primary", details)
    return [AllocationRef.model_validate(a) for a in _server_allocations(db, server.id)]
