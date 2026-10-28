"""Zustandsmeldungen eines Agents in den Status der Server übersetzen."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentlink.protocol import StateFrame
from app.models import Server
from app.models.egg import Egg
from app.services.startup_ready import done_texts


def next_status(
    status: str, state: str, exit_code: int | None, hold: bool = False
) -> tuple[str | None, str | None]:
    """Gibt (neuer Status, Fehlermeldung) zurück. Der Status None heißt: keine Änderung."""
    if state == "running":
        if hold:
            # Das Egg meldet Bereitschaft über die Konsole: bis dahin bleibt es bei "starting".
            return ("starting", None) if status in {"offline", "error"} else (None, None)
        return ("running", None) if status in {"offline", "starting", "error"} else (None, None)
    if state == "exited":
        if status == "stopping":
            return "offline", None
        if status in {"running", "starting"}:
            if exit_code in (0, None):
                return "offline", None
            if exit_code in (126, 127):
                # Der Startbefehl fehlt oder lässt sich nicht ausführen: meist fehlen die
                # Serverdateien (leere oder unvollständige Installation).
                return "error", (
                    "The server stopped right after starting: the startup command was not found. "
                    "The server files may be missing. Try reinstalling the server."
                )
            return "error", f"The container exited with code {exit_code}."
        return None, None
    if state == "created":
        return ("offline", None) if status in {"running", "starting"} else (None, None)
    if state == "removed" and status in {"running", "starting", "stopping"}:
        return "error", "The container was removed."
    return None, None


def apply_state(db: Session, node_id: uuid.UUID, frame: StateFrame) -> str | None:
    """Übernimmt eine Meldung. Gibt den neuen Status zurück, None ohne Änderung."""
    new_status: str | None = None
    try:
        server_id = uuid.UUID(frame.name)
    except ValueError:
        server_id = None
    if server_id is not None:
        # populate_existing: Diese Session lebt lange, andere Requests ändern den Status.
        server = db.scalar(
            select(Server).where(Server.id == server_id).execution_options(populate_existing=True)
        )
        if server is not None and server.node_id == node_id:
            egg = db.get(Egg, server.egg_id)
            hold = bool(egg and done_texts(egg.config))
            new_status, error = next_status(server.status, frame.state, frame.exit_code, hold)
            if new_status is not None:
                server.status = new_status
                server.last_error = error
    db.commit()
    return new_status
