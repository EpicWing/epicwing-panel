"""Zustandsmeldungen eines Agents in den Status der Server übersetzen."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentlink.protocol import StateFrame
from app.models import Server


def next_status(
    status: str, state: str, exit_code: int | None
) -> tuple[str | None, str | None]:
    """Gibt (neuer Status, Fehlermeldung) zurück. Der Status None heißt: keine Änderung."""
    if state == "running":
        return ("running", None) if status in {"offline", "starting", "error"} else (None, None)
    if state == "exited":
        if status == "stopping":
            return "offline", None
        if status in {"running", "starting"}:
            if exit_code in (0, None):
                return "offline", None
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
            new_status, error = next_status(server.status, frame.state, frame.exit_code)
            if new_status is not None:
                server.status = new_status
                server.last_error = error
    db.commit()
    return new_status
