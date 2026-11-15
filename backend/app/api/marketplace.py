"""Marketplace: browse packages from allowed GitHub catalogs and install them as eggs."""

import asyncio
import base64
import posixpath
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.eggs import _insert_egg, _variable_rows
from app.api.servers import FILES_BLOCKED, _conflict, _send
from app.db import get_db
from app.models import Egg, EggVariable, InstalledPackage, Nest, Server, ServerPackage
from app.schemas.egg import EggCreate
from app.schemas.marketplace import (
    DEFAULT_TARGETS,
    INSTALLABLE,
    LEGACY_CATEGORIES,
    SERVER_INSTALLABLE,
    IndexEntry,
    Manifest,
)
from app.security.permissions import AdminAuth
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import audit, eggio, lifecycle
from app.services import marketplace as market
from app.services import startup as startup_service

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

DbSession = Annotated[Session, Depends(get_db)]

DEFAULT_NEST = "Marketplace"


class PackageOut(BaseModel):
    id: str
    name: str
    description: str
    version: str
    author: str
    category: str
    repository: str
    license: str
    tags: list[str]
    game: str | None
    loaders: list[str]
    game_versions: list[str]
    downloads: int | None
    updated_at: str | None
    registry: str
    commit: str
    installable: bool
    server_installable: bool
    installed: bool
    update_available: bool


class InstalledOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: str
    name: str
    version: str
    category: str
    repository: str
    commit: str
    egg_id: uuid.UUID | None
    installed_at: datetime
    warnings: list[str] = []
    latest_version: str | None = None


class Facet(BaseModel):
    value: str
    count: int


class CatalogOut(BaseModel):
    registries: list[str]
    total: int
    tag_options: list[Facet]
    author_options: list[Facet]
    game_options: list[Facet]
    loader_options: list[Facet]
    version_options: list[Facet]
    category_options: list[Facet]
    packages: list[PackageOut]
    installed: list[InstalledOut]
    errors: list[str]


class PackageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry: str
    package_id: str


class InstallIn(PackageRef):
    nest_id: uuid.UUID | None = None


class PreviewVariable(BaseModel):
    env_variable: str
    name: str
    default_value: str
    secret: bool


class PreviewOut(BaseModel):
    name: str
    description: str
    version: str
    author: str
    license: str
    category: str
    repository: str
    commit: str
    docker_image: str
    startup: str
    stop_command: str
    install_script: str
    variables: list[PreviewVariable]
    warnings: list[str]


def _load(registry: str, package_id: str) -> tuple[IndexEntry, Manifest]:
    try:
        entry = next((e for e in market.fetch_catalog(registry) if e.id == package_id), None)
        if entry is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found in this catalog.")
        return entry, market.fetch_manifest(entry)
    except market.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None


def _target_path(manifest: Manifest) -> str:
    """Where a plugin or mod lands in the server, for example plugins/LuckPerms.jar."""
    if manifest.file is None:
        raise HTTPException(422, "This package has no file.")
    folder = manifest.file.target or DEFAULT_TARGETS.get(manifest.category, "plugins")
    return f"{folder}/{manifest.file.name}"


def _prepare(entry: IndexEntry, manifest: Manifest) -> tuple[dict, str, list[str]]:
    """The egg fields of a package, ready for EggCreate, plus its config and hints."""
    if manifest.category not in INSTALLABLE or manifest.egg is None:
        raise HTTPException(422, "Packages of this category cannot be installed yet.")
    try:
        fields, config, warnings = eggio.import_egg(market.fetch_egg(entry, manifest))
    except market.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return fields, config, warnings


def _egg_create(nest_id: uuid.UUID, fields: dict, warnings: list[str]) -> EggCreate:
    try:
        create = EggCreate(nest_id=nest_id, **fields)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        reason = first["msg"].removeprefix("Value error, ")
        raise HTTPException(422, f"The egg is invalid ({where}): {reason}") from None
    unknown = startup_service.unknown(create.startup, [v.env_variable for v in create.variables])
    if unknown:
        warnings.append(f"Placeholders in the start command that are not replaced: {unknown}.")
    return create


def _nest_for(db: Session, nest_id: uuid.UUID | None) -> Nest:
    if nest_id is not None:
        nest = db.get(Nest, nest_id)
        if nest is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nest not found.")
        return nest
    nest = db.scalar(select(Nest).where(Nest.name == DEFAULT_NEST))
    if nest is None:
        nest = Nest(name=DEFAULT_NEST, description="Packages from the marketplace")
        db.add(nest)
        db.flush()
    return nest


MAX_FACETS = 60


def _haystack(entry: IndexEntry) -> str:
    return f"{entry.name} {entry.description} {entry.author} {' '.join(entry.tags)}".lower()


def _by_name(row: tuple[str, IndexEntry]) -> tuple[str, str]:
    return (row[1].name.lower(), row[1].id)


def _by_downloads(row: tuple[str, IndexEntry]) -> int:
    return row[1].downloads or 0


def _by_date(row: tuple[str, IndexEntry]) -> str:
    return row[1].updated_at or ""


SORT_KEYS = {"name": _by_name, "popular": _by_downloads, "newest": _by_date}


def _version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts = value.replace("+", ".").replace("-", ".").split(".")
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts)


def _version_facets(values: list[str]) -> list[Facet]:
    counts = Counter(values)
    ranked = sorted(counts, key=_version_key, reverse=True)
    return [Facet(value=v, count=counts[v]) for v in ranked[:MAX_FACETS]]


def _facets(values: list[str]) -> list[Facet]:
    ranked = sorted(Counter(values).items(), key=lambda item: (-item[1], item[0].lower()))
    return [Facet(value=value, count=count) for value, count in ranked[:MAX_FACETS]]


@router.get("")
def catalog(
    _auth: AdminAuth,
    db: DbSession,
    q: Annotated[str, Query(max_length=64)] = "",
    category: Annotated[str, Query(max_length=32)] = "",
    tag: Annotated[list[str] | None, Query(max_length=8)] = None,
    author: Annotated[str, Query(max_length=64)] = "",
    game: Annotated[str, Query(max_length=32)] = "",
    loader: Annotated[str, Query(max_length=24)] = "",
    version: Annotated[str, Query(max_length=24)] = "",
    sort: Annotated[str, Query(pattern="^(newest|popular|name)$")] = "newest",
    order: Annotated[str, Query(pattern="^(asc|desc)?$")] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    refresh: bool = False,
) -> CatalogOut:
    """One page of the catalog. Only the catalog file is loaded, never single packages."""
    records = {p.package_id: p for p in db.scalars(select(InstalledPackage))}
    registries = market.registries()
    rows: list[tuple[str, IndexEntry]] = []
    errors: list[str] = []
    for registry in registries:
        try:
            rows.extend((registry, e) for e in market.fetch_catalog(registry, force=refresh))
        except market.MarketplaceError as exc:
            errors.append(f"{registry}: {exc}")
    # Newest version per package, before any filter, for the Installed tab.
    latest = {e.id: e.version for _reg, e in rows}
    needle = q.strip().lower()
    if needle:
        rows = [row for row in rows if needle in _haystack(row[1])]
    # Counted before the type filter, so the sidebar shows every type.
    category_options = _facets([e.category for _reg, e in rows])
    if category:
        wanted = LEGACY_CATEGORIES.get(category, category)
        rows = [row for row in rows if row[1].category == wanted]
    # The choices for the filters come from the rows before the tag and author filter,
    # so the person can still change their mind.
    tag_options = _facets([t for _reg, e in rows for t in set(e.tags)])
    author_options = _facets([e.author for _reg, e in rows])
    game_options = _facets([e.game for _reg, e in rows if e.game])
    loader_options = _facets([x for _reg, e in rows for x in e.loaders])
    version_options = _version_facets([x for _reg, e in rows for x in e.game_versions])
    for wanted in {t.strip().lower() for t in tag or []}:
        rows = [row for row in rows if wanted in row[1].tags]
    if author.strip():
        rows = [row for row in rows if row[1].author.lower() == author.strip().lower()]
    if game.strip():
        rows = [row for row in rows if row[1].game == game.strip().lower()]
    if loader.strip():
        rows = [row for row in rows if loader.strip().lower() in row[1].loaders]
    if version.strip():
        rows = [row for row in rows if version.strip() in row[1].game_versions]
    # Equal values keep the order by name, because Python's sort is stable.
    rows.sort(key=_by_name)
    descending = order == "desc" if order else sort != "name"
    rows.sort(key=SORT_KEYS[sort], reverse=descending)
    packages = []
    for registry, entry in rows[offset : offset + limit]:
        have = records.get(entry.id)
        packages.append(
            PackageOut(
                id=entry.id,
                name=entry.name,
                description=entry.description,
                version=entry.version,
                author=entry.author,
                category=entry.category,
                repository=entry.repo,
                license=entry.license,
                tags=entry.tags,
                game=entry.game,
                loaders=entry.loaders,
                game_versions=entry.game_versions,
                downloads=entry.downloads,
                updated_at=entry.updated_at,
                registry=registry,
                commit=entry.commit,
                installable=entry.category in INSTALLABLE,
                server_installable=entry.category in SERVER_INSTALLABLE,
                installed=have is not None,
                update_available=have is not None and have.version != entry.version,
            )
        )
    installed = []
    for record in records.values():
        out = InstalledOut.model_validate(record)
        out.latest_version = latest.get(record.package_id)
        installed.append(out)
    return CatalogOut(
        registries=registries,
        total=len(rows),
        tag_options=tag_options,
        author_options=author_options,
        game_options=game_options,
        loader_options=loader_options,
        version_options=version_options,
        category_options=category_options,
        packages=packages,
        installed=installed,
        errors=errors,
    )


@router.post("/preview")
def preview(body: PackageRef, _auth: AdminAuth) -> PreviewOut:
    """Shows what a package would install, without installing anything."""
    entry, manifest = _load(body.registry, body.package_id)
    if manifest.category in SERVER_INSTALLABLE:
        return PreviewOut(
            name=manifest.name,
            description=manifest.description,
            version=manifest.version,
            author=manifest.author,
            license=manifest.license,
            category=manifest.category,
            repository=manifest.repository,
            commit=entry.commit,
            docker_image="",
            startup="",
            stop_command="",
            install_script="",
            variables=[],
            warnings=[f"Copies {_target_path(manifest)} into the server you choose."],
        )
    fields, _config, warnings = _prepare(entry, manifest)
    return PreviewOut(
        name=fields["name"],
        description=manifest.description,
        version=manifest.version,
        author=manifest.author,
        license=manifest.license,
        category=manifest.category,
        repository=manifest.repository,
        commit=entry.commit,
        docker_image=fields["docker_image"],
        startup=fields["startup"],
        stop_command=fields["stop_command"],
        install_script=fields["install_script"],
        variables=[
            PreviewVariable(
                env_variable=v["env_variable"],
                name=v["name"],
                default_value=v["default_value"],
                secret=bool(v.get("secret")),
            )
            for v in fields["variables"]
        ],
        warnings=warnings,
    )


@router.post("/install", status_code=status.HTTP_201_CREATED)
def install(body: InstallIn, request: Request, auth: AdminAuth, db: DbSession) -> InstalledOut:
    if db.scalar(select(InstalledPackage.id).where(InstalledPackage.package_id == body.package_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This package is already installed.")
    entry, manifest = _load(body.registry, body.package_id)
    fields, config, warnings = _prepare(entry, manifest)
    nest = _nest_for(db, body.nest_id)
    create = _egg_create(nest.id, fields, warnings)
    egg = _insert_egg(create, config, request, auth, db, "marketplace.install")
    record = InstalledPackage(
        package_id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        category=manifest.category,
        repository=manifest.repository,
        commit=entry.commit,
        egg_id=egg.id,
        installed_by=auth.user.id,
    )
    db.add(record)
    db.commit()
    out = InstalledOut.model_validate(record)
    out.warnings = warnings
    return out


def _locate(record: InstalledPackage) -> tuple[str, IndexEntry]:
    """The catalog and the current entry of an installed package."""
    for registry in market.registries():
        try:
            entries = market.fetch_catalog(registry)
        except market.MarketplaceError:
            continue
        for entry in entries:
            if entry.id == record.package_id and entry.repo.lower() == record.repository.lower():
                return registry, entry
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, "The package is no longer in an allowed catalog."
    )


@router.post("/installed/{record_id}/update")
def update_package(
    record_id: uuid.UUID, request: Request, auth: AdminAuth, db: DbSession
) -> InstalledOut:
    """Brings the egg of a package to the version in the catalog.

    Existing servers keep their image and start command. New servers and reinstalls
    use the new version. The values of the servers stay, they are stored per server.
    """
    record = db.get(InstalledPackage, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found.")
    registry, current = _locate(record)
    if current.version == record.version and current.commit == record.commit:
        raise HTTPException(status.HTTP_409_CONFLICT, "This package is already up to date.")
    egg = db.get(Egg, record.egg_id) if record.egg_id else None
    if egg is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The egg of this package was deleted. Remove the package and install it again.",
        )
    entry, manifest = _load(registry, current.id)
    fields, config, warnings = _prepare(entry, manifest)
    update = _egg_create(egg.nest_id, fields, warnings)
    egg.description = update.description
    egg.docker_image = update.docker_image
    egg.startup = update.startup
    egg.stop_command = update.stop_command
    egg.install_script = update.install_script
    egg.config = config
    db.execute(delete(EggVariable).where(EggVariable.egg_id == egg.id))
    db.add_all(_variable_rows(egg.id, update.variables))
    old_version = record.version
    record.version = manifest.version
    record.commit = entry.commit
    record.name = manifest.name
    db.commit()
    audit.record(
        db,
        "marketplace.update",
        actor_id=auth.user.id,
        target_type="marketplace_package",
        target_id=str(record.id),
        ip=audit.client_ip(request),
        details={"package": record.package_id, "from": old_version, "to": record.version},
    )
    db.commit()
    out = InstalledOut.model_validate(record)
    out.warnings = warnings
    out.latest_version = record.version
    return out


@router.delete("/installed/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(record_id: uuid.UUID, request: Request, auth: AdminAuth, db: DbSession) -> None:
    record = db.get(InstalledPackage, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found.")
    if record.egg_id is not None:
        in_use = db.scalar(
            select(func.count()).select_from(Server).where(Server.egg_id == record.egg_id)
        )
        if in_use:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{in_use} server(s) still use the egg of this package."
            )
        db.execute(delete(Egg).where(Egg.id == record.egg_id))
    name, package_id = record.name, record.package_id
    db.delete(record)
    db.commit()
    audit.record(
        db,
        "marketplace.remove",
        actor_id=auth.user.id,
        target_type="marketplace_package",
        target_id=str(record_id),
        ip=audit.client_ip(request),
        details={"name": name, "package": package_id},
    )


FilesWrite = Annotated[ServerAccess, Depends(server_access(ServerPermission.FILES_WRITE))]
# Decoded bytes per write. The base64 text must stay below the message limit of the node.
WRITE_CHUNK = 448 * 1024


class ServerInstallOut(BaseModel):
    path: str
    size: int


async def _file_op(server: Server, action: str, **params: object) -> str | None:
    """Runs a file command on the node. Returns the error text, or None when it worked."""
    result = await _send(server, action, {"name": lifecycle.container_name(server.id), **params})
    return None if result.ok else result.error or "The node refused the file operation."


@router.post("/servers/{server_id}")
async def install_to_server(
    body: PackageRef, request: Request, access: FilesWrite, db: DbSession
) -> ServerInstallOut:
    """Copies a plugin or mod from a catalog into a server, checked against its checksum."""
    server = access.server
    if server.status in FILES_BLOCKED:
        raise _conflict("Install the server first.")
    entry, manifest = await asyncio.to_thread(_load, body.registry, body.package_id)
    if manifest.category not in SERVER_INSTALLABLE or manifest.file is None:
        raise HTTPException(422, "This package cannot be added to a server.")
    try:
        data = await asyncio.to_thread(market.fetch_content, entry, manifest)
    except market.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    target = _target_path(manifest)
    current = ""
    for part in posixpath.dirname(target).split("/"):
        current = f"{current}/{part}" if current else part
        error = await _file_op(server, "file.mkdir", path=current)
        if error and "exist" not in error.lower():
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"The folder could not be created: {error}"
            )
    staging = target + ".part"
    for offset in range(0, max(len(data), 1), WRITE_CHUNK):
        chunk = base64.b64encode(data[offset : offset + WRITE_CHUNK]).decode()
        error = await _file_op(
            server,
            "file.write",
            path=staging,
            offset=offset,
            data=chunk,
            create=offset == 0,
            truncate=offset == 0,
        )
        if error:
            await _file_op(server, "file.delete", path=staging)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"The file could not be written: {error}"
            )
    # An older version of the same file is replaced. A missing file is fine.
    await _file_op(server, "file.delete", path=target)
    error = await _file_op(server, "file.rename", path=staging, to=target)
    if error:
        await _file_op(server, "file.delete", path=staging)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The file could not be put in place: {error}"
        )
    record = db.scalar(
        select(ServerPackage).where(
            ServerPackage.server_id == server.id, ServerPackage.package_id == entry.id
        )
    )
    if record is not None and record.path != target:
        # The new version has another file name: the old file goes.
        await _file_op(server, "file.delete", path=record.path)
    if record is None:
        record = ServerPackage(server_id=server.id, package_id=entry.id)
        db.add(record)
    record.registry = body.registry
    record.name = manifest.name
    record.version = manifest.version
    record.category = manifest.category
    record.path = target
    record.sha256 = manifest.file.sha256
    record.installed_at = datetime.now(UTC)
    audit.record(
        db,
        "server.plugin.install",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"package": entry.id, "version": entry.version, "path": target},
    )
    db.commit()
    return ServerInstallOut(path=target, size=len(data))


FilesRead = Annotated[ServerAccess, Depends(server_access(ServerPermission.FILES_READ))]


class ServerPackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: str
    registry: str
    name: str
    version: str
    category: str
    path: str
    installed_at: datetime
    latest_version: str | None = None


@router.get("/servers/{server_id}")
def server_packages(access: FilesRead, db: DbSession) -> list[ServerPackageOut]:
    """The plugins and mods of a server, with the newest version from the catalog."""
    rows = list(
        db.scalars(
            select(ServerPackage)
            .where(ServerPackage.server_id == access.server.id)
            .order_by(ServerPackage.name)
        )
    )
    allowed = set(market.registries())
    latest: dict[tuple[str, str], str] = {}
    for registry in {row.registry for row in rows} & allowed:
        try:
            for entry in market.fetch_catalog(registry):
                latest[(registry, entry.id)] = entry.version
        except market.MarketplaceError:
            continue
    out = []
    for row in rows:
        item = ServerPackageOut.model_validate(row)
        item.latest_version = latest.get((row.registry, row.package_id))
        out.append(item)
    return out


@router.delete("/servers/{server_id}/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_server_package(
    record_id: uuid.UUID, request: Request, access: FilesWrite, db: DbSession
) -> None:
    """Deletes the file of a plugin or mod and forgets it."""
    server = access.server
    row = db.get(ServerPackage, record_id)
    if row is None or row.server_id != server.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plugin not found.")
    if server.status in FILES_BLOCKED:
        raise _conflict("Install the server first.")
    error = await _file_op(server, "file.delete", path=row.path)
    if error and not any(text in error.lower() for text in ("no such", "not exist", "not found")):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"The file could not be deleted: {error}")
    name, path = row.name, row.path
    db.delete(row)
    audit.record(
        db,
        "server.plugin.remove",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"name": name, "path": path},
    )
    db.commit()
