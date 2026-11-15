"""Import users, nodes, eggs, servers and subusers from a Pterodactyl or Pelican database.

The source database is only read. Without --apply nothing is saved (dry run).
Server data stays on the old nodes; the report lists the copy commands per node.
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Allocation, Egg, EggVariable, Nest, Node, Server, ServerVariable, User
from app.models.server import ServerMember, ServerMemberPermission
from app.security.server_access import ALL_SERVER_PERMISSIONS, ServerPermission
from app.services import eggio

PTERO_DATA = "/var/lib/pterodactyl/volumes"
EPICWING_DATA = "/var/lib/epicwing/servers"
FALLBACK_NEST = "Imported"

# Pterodactyl subuser permission -> EpicWing server permissions.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "websocket.connect": ("console.view",),
    "control.console": ("console.view", "console.command"),
    "control.start": ("power.start",),
    "control.stop": ("power.stop",),
    "control.restart": ("power.restart",),
    "file.read": ("files.read",),
    "file.read-content": ("files.read",),
    "file.sftp": ("files.read", "files.write"),
    "file.create": ("files.write",),
    "file.update": ("files.write",),
    "file.delete": ("files.write",),
    "file.archive": ("files.write",),
    "backup.read": ("backups.view",),
    "backup.create": ("backups.create",),
    "backup.download": ("backups.download",),
    "backup.restore": ("backups.restore",),
    "backup.delete": ("backups.delete",),
    "allocation.read": ("allocations.view",),
    "allocation.create": ("allocations.manage",),
    "allocation.update": ("allocations.manage",),
    "allocation.delete": ("allocations.manage",),
    "startup.read": ("startup.view",),
    "startup.update": ("startup.update",),
    "startup.docker-image": ("startup.update",),
    "database.read": ("databases.view",),
    "database.create": ("databases.manage",),
    "database.update": ("databases.manage",),
    "database.delete": ("databases.manage",),
    "database.view_password": ("databases.manage",),
    "schedule.read": ("schedules.view",),
    "schedule.create": ("schedules.manage",),
    "schedule.update": ("schedules.manage",),
    "schedule.delete": ("schedules.manage",),
    "user.read": ("access.view",),
    "user.create": ("access.manage",),
    "user.update": ("access.manage",),
    "user.delete": ("access.manage",),
    "settings.rename": ("settings.view", "settings.update"),
    "settings.reinstall": ("settings.reinstall",),
}
GRANTABLE = ALL_SERVER_PERMISSIONS - {ServerPermission.VIEW.value}


@dataclass
class Report:
    created: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    warnings: list[str] = field(default_factory=list)
    totp_users: list[str] = field(default_factory=list)
    # node name -> server ids whose data has to be copied
    copies: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


def _rows(src: Connection, table: str) -> list[dict[str, Any]]:
    if not inspect(src).has_table(table):
        return []
    return [dict(r._mapping) for r in src.execute(text(f"SELECT * FROM {table}"))]  # noqa: S608


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, list | dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _limit(value: Any, over: Any) -> int | None:
    size = int(value or 0)
    extra = int(over or 0)
    if size <= 0 or extra < 0:
        return None
    return size * (100 + extra) // 100


def _egg_export(
    egg: dict[str, Any], by_id: dict[Any, dict[str, Any]], variables: list[dict]
) -> dict:
    """Builds a PTDL_v2 export from the database rows, with inherited config and script."""

    def pick(key: str, parent_key: str, default: str) -> str:
        value = egg.get(key)
        parent = by_id.get(egg.get(parent_key))
        if (value is None or value == "") and parent is not None:
            value = parent.get(key)
        return default if value is None or value == "" else str(value)

    images = _json(egg.get("docker_images"), {})
    if isinstance(images, list):
        images = {str(i): str(i) for i in images}
    if not images and egg.get("docker_image"):
        images = {"default": str(egg["docker_image"])}
    rules = []
    for v in variables:
        raw_rules = _json(v.get("rules"), v.get("rules"))
        rules.append({
            "name": v.get("name"),
            "description": v.get("description") or "",
            "env_variable": v.get("env_variable"),
            "default_value": v.get("default_value") or "",
            "user_viewable": bool(v.get("user_viewable", True)),
            "user_editable": bool(v.get("user_editable", True)),
            "rules": "|".join(raw_rules) if isinstance(raw_rules, list) else str(raw_rules or ""),
        })
    return {
        "meta": {"version": "PTDL_v2"},
        "name": egg.get("name"),
        "description": egg.get("description") or "",
        "features": _json(egg.get("features"), []),
        "docker_images": images,
        "startup": egg.get("startup") or "",
        "config": {
            "files": pick("config_files", "config_from", "{}"),
            "startup": pick("config_startup", "config_from", "{}"),
            "logs": pick("config_logs", "config_from", "{}"),
            "stop": pick("config_stop", "config_from", "^C"),
        },
        "scripts": {
            "installation": {
                "script": pick("script_install", "copy_script_from", ""),
                "container": pick("script_container", "copy_script_from", "alpine:3.4"),
                "entrypoint": pick("script_entry", "copy_script_from", "ash"),
            }
        },
        "variables": rules,
    }


def _nest(db: Session, name: str) -> Nest:
    nest = db.scalar(select(Nest).where(Nest.name == name))
    if nest is None:
        nest = Nest(name=name)
        db.add(nest)
        db.flush()
    return nest


def run(src: Connection, db: Session) -> Report:
    """Copies everything into the session. The caller commits or rolls back."""
    report = Report()

    # Users. Pterodactyl and Pelican use bcrypt, which the login accepts and upgrades.
    users = {u.email: u.id for u in db.scalars(select(User))}
    user_map: dict[Any, uuid.UUID] = {}
    for row in _rows(src, "users"):
        email = str(row.get("email") or "").strip().lower()
        if "@" not in email:
            report.warnings.append(f"User {row.get('id')} skipped: no valid e-mail address.")
            continue
        if email in users:
            user_map[row["id"]] = users[email]
            report.skipped["users"] += 1
            continue
        user = User(
            email=email,
            password_hash=str(row.get("password") or "!"),
            is_admin=bool(row.get("root_admin")),
        )
        db.add(user)
        db.flush()
        users[email] = user.id
        user_map[row["id"]] = user.id
        report.created["users"] += 1
        if row.get("use_totp"):
            report.totp_users.append(email)

    # Nodes, created as "pending" until the EpicWing agent is enrolled.
    locations = {r["id"]: str(r.get("short") or "") for r in _rows(src, "locations")}
    ptero_allocations = _rows(src, "allocations")
    ports: dict[Any, list[int]] = defaultdict(list)
    for a in ptero_allocations:
        ports[a["node_id"]].append(int(a["port"]))
    nodes = {n.name: n for n in db.scalars(select(Node))}
    node_map: dict[Any, Node] = {}
    for row in _rows(src, "nodes"):
        name = str(row.get("name") or f"node-{row['id']}")[:64]
        if name in nodes:
            node_map[row["id"]] = nodes[name]
            report.skipped["nodes"] += 1
            continue
        used = ports.get(row["id"]) or [25565]
        node = Node(
            name=name,
            location=locations.get(row.get("location_id"), "")[:64],
            fqdn=str(row["fqdn"])[:255] if row.get("fqdn") else None,
            status="pending",
            ram_limit_mb=_limit(row.get("memory"), row.get("memory_overallocate")),
            disk_limit_mb=_limit(row.get("disk"), row.get("disk_overallocate")),
            port_range_start=min(used),
            port_range_end=max(used),
        )
        db.add(node)
        db.flush()
        nodes[name] = node
        node_map[row["id"]] = node
        report.created["nodes"] += 1

    # Allocations
    taken = {(a.node_id, a.ip, a.port): a for a in db.scalars(select(Allocation))}
    alloc_map: dict[Any, Allocation] = {}
    for a in ptero_allocations:
        node = node_map.get(a["node_id"])
        if node is None:
            continue
        key = (node.id, str(a["ip"])[:45], int(a["port"]))
        if key in taken:
            alloc_map[a["id"]] = taken[key]
            report.skipped["allocations"] += 1
            continue
        alloc = Allocation(node_id=key[0], ip=key[1], port=key[2])
        db.add(alloc)
        taken[key] = alloc
        alloc_map[a["id"]] = alloc
        report.created["allocations"] += 1
    db.flush()

    # Nests and eggs. Pelican has no nests, its eggs land in one nest.
    nest_names = {r["id"]: str(r.get("name") or FALLBACK_NEST)[:64] for r in _rows(src, "nests")}
    egg_rows = _rows(src, "eggs")
    egg_by_id = {e["id"]: e for e in egg_rows}
    var_rows = _rows(src, "egg_variables")
    vars_by_egg: dict[Any, list[dict]] = defaultdict(list)
    env_by_var: dict[Any, str] = {}
    for v in var_rows:
        vars_by_egg[v["egg_id"]].append(v)
        env_by_var[v["id"]] = str(v.get("env_variable") or "")
    egg_map: dict[Any, Egg] = {}
    for row in egg_rows:
        try:
            fields, config, hints = eggio.import_egg(
                _egg_export(row, egg_by_id, vars_by_egg[row["id"]])
            )
        except ValueError as exc:
            report.warnings.append(f"Egg {row.get('name')} skipped: {exc}")
            continue
        report.warnings.extend(f"Egg {fields['name']}: {h}" for h in hints)
        nest = _nest(db, nest_names.get(row.get("nest_id"), FALLBACK_NEST))
        found = db.scalar(select(Egg).where(Egg.nest_id == nest.id, Egg.name == fields["name"]))
        if found is not None:
            egg_map[row["id"]] = found
            report.skipped["eggs"] += 1
            continue
        variables = fields.pop("variables")
        egg = Egg(nest_id=nest.id, config=config, **fields)
        db.add(egg)
        db.flush()
        for variable in variables:
            db.add(EggVariable(egg_id=egg.id, **variable))
        egg_map[row["id"]] = egg
        report.created["eggs"] += 1

    # Servers keep their UUID, so the data folder has the same name on both sides.
    known = set(db.scalars(select(Server.id)))
    server_map: dict[Any, uuid.UUID] = {}
    for row in _rows(src, "servers"):
        try:
            server_id = uuid.UUID(str(row.get("uuid")))
        except ValueError:
            report.warnings.append(f"Server {row.get('name')} skipped: invalid UUID.")
            continue
        if server_id in known:
            server_map[row["id"]] = server_id
            report.skipped["servers"] += 1
            continue
        owner = user_map.get(row.get("owner_id"))
        node = node_map.get(row.get("node_id"))
        egg = egg_map.get(row.get("egg_id"))
        if owner is None or node is None or egg is None:
            report.warnings.append(
                f"Server {row.get('name')} skipped: its owner, node or egg was not imported."
            )
            continue
        db.add(
            Server(
                id=server_id,
                name=str(row.get("name") or "Server")[:64],
                description=str(row.get("description") or "")[:255],
                owner_id=owner,
                node_id=node.id,
                egg_id=egg.id,
                image=str(row.get("image") or egg.docker_image)[:255],
                startup=str(row.get("startup") or egg.startup)[:2048],
                memory_mb=min(max(int(row.get("memory") or 0), 0), 65536),
                cpus=min(max(int(row.get("cpu") or 0), 0) / 100, 64.0),
                disk_mb=min(max(int(row.get("disk") or 0), 0), 10_000_000),
                backup_limit=max(int(row.get("backup_limit") or 0), 0),
                status="new",
            )
        )
        db.flush()
        known.add(server_id)
        server_map[row["id"]] = server_id
        report.created["servers"] += 1
        report.copies[node.name].append(str(server_id))
        for a in ptero_allocations:
            alloc = alloc_map.get(a["id"])
            if a.get("server_id") == row["id"] and alloc is not None:
                alloc.server_id = server_id
                alloc.is_primary = a["id"] == row.get("allocation_id")

    new_servers = {sid for sids in report.copies.values() for sid in sids}

    for row in _rows(src, "server_variables"):
        server_id = server_map.get(row.get("server_id"))
        env = env_by_var.get(row.get("variable_id"))
        if server_id is None or str(server_id) not in new_servers or not env:
            continue
        db.add(
            ServerVariable(
                server_id=server_id,
                env_variable=env,
                value=str(row.get("variable_value") or "")[:8192],
            )
        )

    for row in _rows(src, "subusers"):
        server_id = server_map.get(row.get("server_id"))
        user_id = user_map.get(row.get("user_id"))
        if server_id is None or user_id is None or str(server_id) not in new_servers:
            continue
        granted = {
            p for old in _json(row.get("permissions"), []) for p in PERMISSIONS.get(str(old), ())
        } & GRANTABLE
        member = ServerMember(server_id=server_id, user_id=user_id)
        db.add(member)
        db.flush()
        for permission in sorted(granted):
            db.add(ServerMemberPermission(member_id=member.id, permission=permission))
        report.created["subusers"] += 1

    db.flush()
    return report


def print_report(report: Report, applied: bool) -> None:
    print("Saved." if applied else "Dry run, nothing was saved. Add --apply to import.")
    for kind in ("users", "nodes", "allocations", "eggs", "servers", "subusers"):
        new, old = report.created[kind], report.skipped[kind]
        print(f"  {kind:<12} {new:>5} new   {old:>5} already there")
    if report.warnings:
        print("\nWarnings:")
        for line in report.warnings:
            print(f"  - {line}")
    if report.totp_users:
        print("\nThese users had 2FA and must set it up again:")
        for email in report.totp_users:
            print(f"  - {email}")
    if report.copies:
        print("\nNext steps per node: enroll the EpicWing agent, stop Wings, copy the data,")
        print("then press Install on each server in the panel.")
        for node, servers in report.copies.items():
            print(f"\n  # {node}")
            print("  systemctl stop wings && systemctl disable wings")
            for sid in servers:
                print(f"  rsync -a {PTERO_DATA}/{sid}/ {EPICWING_DATA}/{sid}/")


def main(source: str, apply: bool) -> int:
    engine = create_engine(source)
    with engine.connect() as src, Session(get_engine()) as db:
        report = run(src, db)
        if apply:
            db.commit()
        else:
            db.rollback()
    print_report(report, apply)
    return 0
