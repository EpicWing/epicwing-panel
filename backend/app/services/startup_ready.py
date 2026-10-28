"""Bereitmeldung eines Servers: Erst wenn die Konsole den "done"-Text des Eggs zeigt, läuft er."""

import json
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Server
from app.models.egg import Egg

# Ohne Bereitzeile (z. B. nach einem Neustart des Panels) gilt der Server danach als bereit.
FALLBACK_SECONDS = 300
TAIL_CHARS = 256


def done_texts(config_text: str | None) -> tuple[str, ...]:
    """Liest startup.done aus der Egg-Config (Text oder Liste, auch als JSON-Text gespeichert)."""
    try:
        config = json.loads(config_text or "{}")
    except ValueError:
        return ()
    if not isinstance(config, dict):
        return ()
    startup = config.get("startup")
    if isinstance(startup, str):
        try:
            startup = json.loads(startup)
        except ValueError:
            return ()
    if not isinstance(startup, dict):
        return ()
    done = startup.get("done")
    items = done if isinstance(done, list) else [done]
    return tuple(item for item in items if isinstance(item, str) and item)


@dataclass
class _Watch:
    texts: tuple[str, ...]
    since: float
    tail: str = ""


class ReadyWatcher:
    """Merkt sich im Speicher, welche Container noch auf ihre Bereitmeldung warten."""

    def __init__(self) -> None:
        self._watches: dict[str, _Watch] = {}

    def watching(self, name: str) -> bool:
        return name in self._watches

    def watch(self, name: str, texts: tuple[str, ...], now: float) -> None:
        if name not in self._watches:
            self._watches[name] = _Watch(texts, now)

    def forget(self, name: str) -> None:
        self._watches.pop(name, None)

    def feed(self, name: str, data: str) -> bool:
        """True, wenn die Ausgabe die Bereitmeldung enthält. Der Eintrag wird dann entfernt."""
        watch = self._watches.get(name)
        if watch is None:
            return False
        text = watch.tail + data
        if any(t in text for t in watch.texts):
            del self._watches[name]
            return True
        watch.tail = text[-TAIL_CHARS:]
        return False

    def expired(self, name: str, now: float) -> bool:
        watch = self._watches.get(name)
        return watch is not None and now - watch.since >= FALLBACK_SECONDS


watcher = ReadyWatcher()


def _server(db: Session, node_id: uuid.UUID, name: str) -> Server | None:
    try:
        server_id = uuid.UUID(name)
    except ValueError:
        return None
    server = db.get(Server, server_id)
    return server if server is not None and server.node_id == node_id else None


def register(db: Session, node_id: uuid.UUID, name: str, state: str) -> None:
    """Nach einer Zustandsmeldung: auf die Bereitmeldung warten, solange der Server startet."""
    if state != "running":
        watcher.forget(name)
        return
    server = _server(db, node_id, name)
    if server is None or server.status != "starting":
        watcher.forget(name)
        return
    egg = db.get(Egg, server.egg_id)
    texts = done_texts(egg.config) if egg else ()
    if texts:
        watcher.watch(name, texts, time.monotonic())


def mark_running(db: Session, node_id: uuid.UUID, name: str) -> bool:
    """Setzt starting auf running. True, wenn sich der Status geändert hat."""
    watcher.forget(name)
    server = _server(db, node_id, name)
    if server is None:
        return False
    db.refresh(server)
    if server.status != "starting":
        return False
    server.status = "running"
    server.last_error = None
    db.commit()
    return True
