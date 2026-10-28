"""Datenbanken eines Servers: Namen, Zugangsdaten und Aufräumen beim Löschen."""

import asyncio
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DatabaseHost, ServerDatabase
from app.security.vault import decrypt_text
from app.services import dbhost

HOST_PURPOSE = "dbhost"
PASSWORD_PURPOSE = "serverdb"  # noqa: S105 (Schlüssel-Zweck, kein Passwort)


def database_name(server_id: uuid.UUID, name: str) -> str:
    return f"s{server_id.hex[:8]}_{name}"


def endpoint_for(host: DatabaseHost) -> dbhost.Endpoint:
    password = decrypt_text(host.admin_password, HOST_PURPOSE)
    if password is None:
        raise dbhost.HostError("The stored admin password of the database host is unreadable.")
    return dbhost.Endpoint(host.host, host.port, host.admin_user, password)


async def drop_all(db: Session, server_id: uuid.UUID) -> None:
    """Entfernt alle Datenbanken des Servers vom Host, bevor der Server gelöscht wird.

    Schlägt ein Host fehl, bleibt der Server bestehen, damit keine verwaisten
    Datenbanken auf dem Host zurückbleiben.
    """
    rows = list(db.scalars(select(ServerDatabase).where(ServerDatabase.server_id == server_id)))
    for row in rows:
        name = row.name
        try:
            host = db.get(DatabaseHost, row.host_id)
            endpoint = endpoint_for(host)
            await asyncio.to_thread(
                dbhost.drop_database, endpoint, name, row.username, row.remote
            )
        except dbhost.HostError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Could not remove database {name}: {exc}"
            ) from exc
        db.delete(row)
        db.commit()
