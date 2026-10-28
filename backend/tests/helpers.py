"""Hilfen für Tests, die alle Routen der App prüfen."""

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute


@dataclass(frozen=True)
class RouteInfo:
    path: str
    methods: frozenset[str]
    websocket: bool
    dependant: Any


def _from_context(ctx: Any) -> RouteInfo | None:
    """Liest eine Route aus einem _EffectiveRouteContext (eingebundene Router)."""
    original = ctx.original_route
    if isinstance(original, APIRoute):
        # Pfad, Methoden und Abhängigkeiten stehen am Kontext, mit Präfix und
        # den Abhängigkeiten des Includes. starlette_route ist hier None.
        return RouteInfo(ctx.path, frozenset(ctx.methods), False, ctx.dependant)
    route = ctx.starlette_route
    if isinstance(route, APIWebSocketRoute):
        return RouteInfo(route.path, frozenset(), True, route.dependant)
    return None


def _from_route(route: object) -> RouteInfo | None:
    """Liest eine Route, die direkt in app.routes liegt."""
    if isinstance(route, APIRoute):
        return RouteInfo(route.path, frozenset(route.methods), False, route.dependant)
    if isinstance(route, APIWebSocketRoute):
        return RouteInfo(route.path, frozenset(), True, route.dependant)
    return None


def collect_routes(app: FastAPI) -> list[RouteInfo]:
    """Alle HTTP- und WebSocket-Routen mit vollem Pfad, auch aus eingebundenen Routern.

    Der Sammler läuft nie still leer: Er bricht ab, wenn er nichts findet oder ein
    Pfad nicht mit /api beginnt. Docs-Routen von FastAPI gehören nicht dazu.
    """
    found: list[RouteInfo] = []
    for top in app.routes:
        if hasattr(top, "effective_route_contexts"):
            for ctx in top.effective_route_contexts():
                if (info := _from_context(ctx)) is not None:
                    found.append(info)
        elif (info := _from_route(top)) is not None:
            found.append(info)

    if not found:
        raise AssertionError("Routen-Sammler findet nichts")
    bad = [r.path for r in found if not r.path.startswith("/api")]
    if bad:
        raise AssertionError(f"Pfade ohne /api-Präfix, Sammler liest falsch: {bad}")
    if any(r.dependant is None for r in found):
        raise AssertionError("Eine Route hat kein dependant, Auth-Prüfung nicht möglich")
    return found
