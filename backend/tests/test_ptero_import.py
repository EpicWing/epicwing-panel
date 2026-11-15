import json
import uuid

import bcrypt
import pytest
from sqlalchemy import create_engine, select, text

from app import ptero_import
from app.models import Allocation, Egg, EggVariable, Node, Server, ServerVariable, User
from app.models.server import ServerMember, ServerMemberPermission
from app.security.passwords import needs_rehash, verify_password

SERVER_UUID = "9c3f6a52-2b1e-4c3d-8a1f-0d6b7c5e4a21"
SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, root_admin INTEGER,
  use_totp INTEGER);
CREATE TABLE locations (id INTEGER PRIMARY KEY, short TEXT);
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT, fqdn TEXT, location_id INTEGER,
  memory INTEGER, memory_overallocate INTEGER, disk INTEGER, disk_overallocate INTEGER);
CREATE TABLE allocations (id INTEGER PRIMARY KEY, node_id INTEGER, ip TEXT, port INTEGER,
  server_id INTEGER);
CREATE TABLE nests (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE eggs (id INTEGER PRIMARY KEY, nest_id INTEGER, name TEXT, description TEXT,
  docker_images TEXT, startup TEXT, config_files TEXT, config_startup TEXT, config_logs TEXT,
  config_stop TEXT, config_from INTEGER, script_install TEXT, script_container TEXT,
  script_entry TEXT, copy_script_from INTEGER, features TEXT);
CREATE TABLE egg_variables (id INTEGER PRIMARY KEY, egg_id INTEGER, name TEXT,
  description TEXT, env_variable TEXT, default_value TEXT, user_viewable INTEGER,
  user_editable INTEGER, rules TEXT);
CREATE TABLE servers (id INTEGER PRIMARY KEY, uuid TEXT, name TEXT, description TEXT,
  owner_id INTEGER, node_id INTEGER, egg_id INTEGER, image TEXT, startup TEXT, memory INTEGER,
  cpu INTEGER, disk INTEGER, backup_limit INTEGER, allocation_id INTEGER);
CREATE TABLE server_variables (id INTEGER PRIMARY KEY, server_id INTEGER, variable_id INTEGER,
  variable_value TEXT);
CREATE TABLE subusers (id INTEGER PRIMARY KEY, user_id INTEGER, server_id INTEGER,
  permissions TEXT);
"""


def _laravel_hash(password: str) -> str:
    return "$2y$" + bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()[4:]


@pytest.fixture
def source():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(text(statement))
        rows = [
            (
                "INSERT INTO users VALUES (1, 'Admin@Example.com', :pw, 1, 1)",
                {"pw": _laravel_hash("old-panel-password")},
            ),
            (
                "INSERT INTO users VALUES (2, 'friend@example.com', :pw, 0, 0)",
                {"pw": _laravel_hash("friend-password")},
            ),
            ("INSERT INTO locations VALUES (1, 'de')", {}),
            (
                "INSERT INTO nodes VALUES (1, 'node-1', 'n1.example.com', 1, 8192, 0, 100000, -1)",
                {},
            ),
            ("INSERT INTO allocations VALUES (1, 1, '0.0.0.0', 25565, 1)", {}),
            ("INSERT INTO allocations VALUES (2, 1, '0.0.0.0', 25566, 1)", {}),
            ("INSERT INTO allocations VALUES (3, 1, '0.0.0.0', 25570, NULL)", {}),
            ("INSERT INTO nests VALUES (1, 'Minecraft')", {}),
            (
                "INSERT INTO eggs VALUES (1, 1, 'Paper', 'Parent', :img, 'java -jar server.jar',"
                " '{}', '{\"done\": \")! For help\"}', '{}', 'stop', NULL, 'echo install',"
                " 'ghcr.io/ptero-eggs/installers:alpine', 'ash', NULL, '[\"eula\"]')",
                {"img": json.dumps({"Java 21": "ghcr.io/ptero-eggs/yolks:java_21"})},
            ),
            (
                "INSERT INTO eggs VALUES (2, 1, 'Paper Copy', 'Child', :img, 'java -jar s.jar',"
                " NULL, NULL, NULL, NULL, 1, NULL, NULL, NULL, 1, NULL)",
                {"img": json.dumps(["ghcr.io/ptero-eggs/yolks:java_21"])},
            ),
            (
                "INSERT INTO egg_variables VALUES (1, 2, 'Version', '', 'MC_VERSION', 'latest',"
                " 1, 1, 'required|string|max:20')",
                {},
            ),
            (
                "INSERT INTO servers VALUES (1, :uuid, 'Survival', 'Main', 1, 1, 2,"
                " 'ghcr.io/ptero-eggs/yolks:java_21', 'java -Xmx{{SERVER_MEMORY}}M -jar s.jar',"
                " 4096, 200, 20000, 3, 1)",
                {"uuid": SERVER_UUID},
            ),
            ("INSERT INTO server_variables VALUES (1, 1, 1, '1.21.1')", {}),
            (
                "INSERT INTO subusers VALUES (1, 2, 1, :perms)",
                {
                    "perms": json.dumps(
                        ["control.console", "control.start", "file.read", "unknown.x"]
                    )
                },
            ),
        ]
        for statement, params in rows:
            conn.execute(text(statement), params)
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def test_import_copies_everything(source, db_session):
    report = ptero_import.run(source, db_session)
    db_session.commit()

    assert report.created["users"] == 2
    assert report.created["servers"] == 1
    assert report.totp_users == ["admin@example.com"]

    admin = db_session.scalar(select(User).where(User.email == "admin@example.com"))
    assert admin.is_admin
    assert verify_password(admin.password_hash, "old-panel-password")
    assert not verify_password(admin.password_hash, "wrong")
    assert needs_rehash(admin.password_hash)

    node = db_session.scalar(select(Node))
    assert (node.name, node.location, node.status) == ("node-1", "de", "pending")
    assert (node.port_range_start, node.port_range_end) == (25565, 25570)
    assert node.ram_limit_mb == 8192 and node.disk_limit_mb is None

    child = db_session.scalar(select(Egg).where(Egg.name == "Paper Copy"))
    assert child.install_script == "echo install"
    assert ")! For help" in child.config
    assert child.stop_command == "stop"
    env = db_session.scalars(select(EggVariable.env_variable).where(EggVariable.egg_id == child.id))
    assert list(env) == ["MC_VERSION"]

    server = db_session.get(Server, uuid.UUID(SERVER_UUID))
    limits = (server.memory_mb, server.cpus, server.disk_mb, server.status)
    assert limits == (4096, 2.0, 20000, "new")
    assert server.egg_id == child.id
    ports = db_session.execute(
        select(Allocation.port, Allocation.is_primary)
        .where(Allocation.server_id == server.id)
        .order_by(Allocation.port)
    ).all()
    assert [tuple(p) for p in ports] == [(25565, True), (25566, False)]
    variable = db_session.scalar(
        select(ServerVariable).where(ServerVariable.server_id == server.id)
    )
    assert (variable.env_variable, variable.value) == ("MC_VERSION", "1.21.1")

    member = db_session.scalar(select(ServerMember))
    permissions = set(
        db_session.scalars(
            select(ServerMemberPermission.permission).where(
                ServerMemberPermission.member_id == member.id
            )
        )
    )
    assert permissions == {"console.view", "console.command", "power.start", "files.read"}
    assert report.copies == {"node-1": [SERVER_UUID]}


def test_import_twice_creates_nothing_new(source, db_session):
    ptero_import.run(source, db_session)
    db_session.commit()
    again = ptero_import.run(source, db_session)
    assert sum(again.created.values()) == 0
    assert again.skipped["users"] == 2
    assert again.skipped["servers"] == 1
