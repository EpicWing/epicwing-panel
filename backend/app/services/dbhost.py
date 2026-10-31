"""Access to MariaDB/MySQL hosts for server databases.

All functions block; call them from async code with asyncio.to_thread.
Names (database, user, host) are checked strictly. Values like the
password go through the driver as parameters.
"""

import contextlib
import re
import secrets
import string
from dataclasses import dataclass

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
USER_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
REMOTE_RE = re.compile(r"^[A-Za-z0-9%_.:\-]{1,255}$")

PRIVILEGES = (
    "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, "
    "LOCK TABLES, CREATE TEMPORARY TABLES, CREATE VIEW, SHOW VIEW, EXECUTE, TRIGGER"
)
_PASSWORD_CHARS = string.ascii_letters + string.digits


class HostError(Exception):
    """Error when accessing the host. The text contains no credentials."""


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    user: str
    password: str


def new_password() -> str:
    return "".join(secrets.choice(_PASSWORD_CHARS) for _ in range(24))


def random_username() -> str:
    return "u" + secrets.token_hex(6)


def _load():
    try:
        import pymysql
    except ImportError as exc:
        raise HostError("The pymysql package is not installed on the panel.") from exc
    return pymysql


def _connect(endpoint: Endpoint):
    pymysql = _load()
    try:
        return pymysql.connect(
            host=endpoint.host,
            port=endpoint.port,
            user=endpoint.user,
            password=endpoint.password,
            connect_timeout=5,
            read_timeout=20,
            write_timeout=20,
            autocommit=True,
        )
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == 1045:
            raise HostError("The database host rejected the admin login.") from exc
        raise HostError("Could not connect to the database host.") from exc
    except (pymysql.MySQLError, OSError) as exc:
        raise HostError("Could not connect to the database host.") from exc


def _run(endpoint: Endpoint, statements: list[tuple[str, tuple[str, ...] | None]]) -> None:
    pymysql = _load()
    conn = _connect(endpoint)
    try:
        with conn.cursor() as cursor:
            for sql, args in statements:
                cursor.execute(sql, args)
    except pymysql.MySQLError as exc:
        raise HostError("The database host rejected the command.") from exc
    finally:
        conn.close()


def _check(name: str | None = None, user: str | None = None, remote: str | None = None) -> None:
    if name is not None and not NAME_RE.match(name):
        raise ValueError("invalid database name")
    if user is not None and not USER_RE.match(user):
        raise ValueError("invalid user name")
    if remote is not None and not REMOTE_RE.match(remote):
        raise ValueError("invalid host pattern")


def ping(endpoint: Endpoint) -> str:
    """Checks the connection and admin login, returns the server version."""
    pymysql = _load()
    conn = _connect(endpoint)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            row = cursor.fetchone()
    except pymysql.MySQLError as exc:
        raise HostError("The database host rejected the command.") from exc
    finally:
        conn.close()
    return str(row[0]) if row else ""


def create_database(endpoint: Endpoint, name: str, user: str, remote: str, password: str) -> None:
    _check(name, user, remote)
    # In GRANT, _ and % are placeholders for database names; without escaping, the
    # user would also match other databases with similar names.
    grant_name = name.replace("_", "\\_")
    try:
        _run(
            endpoint,
            [
                (
                    f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
                    None,
                ),
                ("CREATE USER %s@%s IDENTIFIED BY %s", (user, remote, password)),
                (f"GRANT {PRIVILEGES} ON `{grant_name}`.* TO %s@%s", (user, remote)),
            ],
        )
    except HostError:
        with contextlib.suppress(HostError):
            drop_database(endpoint, name, user, remote)
        raise


def set_password(endpoint: Endpoint, user: str, remote: str, password: str) -> None:
    _check(user=user, remote=remote)
    _run(endpoint, [("ALTER USER %s@%s IDENTIFIED BY %s", (user, remote, password))])


def drop_database(endpoint: Endpoint, name: str, user: str, remote: str) -> None:
    _check(name, user, remote)
    _run(
        endpoint,
        [
            (f"DROP DATABASE IF EXISTS `{name}`", None),
            ("DROP USER IF EXISTS %s@%s", (user, remote)),
        ],
    )
