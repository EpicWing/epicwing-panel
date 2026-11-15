"""Marketplace: browse packages from allowed GitHub catalogs and install them as eggs."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.eggs import _insert_egg
from app.db import get_db
from app.models import Egg, InstalledPackage, Nest, Server
from app.schemas.egg import EggCreate
from app.schemas.marketplace import INSTALLABLE, IndexEntry, Manifest
from app.security.permissions import AdminAuth
from app.services import audit, eggio
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
    registry: str
    commit: str
    installable: bool
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


class CatalogOut(BaseModel):
    registries: list[str]
    total: int
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


def _haystack(entry: IndexEntry) -> str:
    return f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()


@router.get("")
def catalog(
    _auth: AdminAuth,
    db: DbSession,
    q: Annotated[str, Query(max_length=64)] = "",
    category: Annotated[str, Query(max_length=32)] = "",
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
    needle = q.strip().lower()
    if needle:
        rows = [row for row in rows if needle in _haystack(row[1])]
    if category:
        rows = [row for row in rows if row[1].category == category]
    rows.sort(key=lambda row: (row[1].name.lower(), row[1].id))
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
                registry=registry,
                commit=entry.commit,
                installable=entry.category in INSTALLABLE,
                installed=have is not None,
                update_available=have is not None and have.version != entry.version,
            )
        )
    installed = [InstalledOut.model_validate(p) for p in records.values()]
    return CatalogOut(
        registries=registries,
        total=len(rows),
        packages=packages,
        installed=installed,
        errors=errors,
    )


@router.post("/preview")
def preview(body: PackageRef, _auth: AdminAuth) -> PreviewOut:
    """Shows what a package would install, without installing anything."""
    entry, manifest = _load(body.registry, body.package_id)
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
