"""Helpers for tests that check all routes of the app."""

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
    """Reads a route from an _EffectiveRouteContext (included routers)."""
    original = ctx.original_route
    if isinstance(original, APIRoute):
        # Path, methods and dependencies are on the context, with prefix and
        # the dependencies of the include. starlette_route is None here.
        return RouteInfo(ctx.path, frozenset(ctx.methods), False, ctx.dependant)
    route = ctx.starlette_route
    if isinstance(route, APIWebSocketRoute):
        return RouteInfo(route.path, frozenset(), True, route.dependant)
    return None


def _from_route(route: object) -> RouteInfo | None:
    """Reads a route that sits directly in app.routes."""
    if isinstance(route, APIRoute):
        return RouteInfo(route.path, frozenset(route.methods), False, route.dependant)
    if isinstance(route, APIWebSocketRoute):
        return RouteInfo(route.path, frozenset(), True, route.dependant)
    return None


def collect_routes(app: FastAPI) -> list[RouteInfo]:
    """All HTTP and WebSocket routes with the full path, also from included routers.

    The collector never runs empty quietly: it stops if it finds nothing or if a
    path does not start with /api. FastAPI docs routes do not count.
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
        raise AssertionError(f"Paths without /api prefix, collector reads wrong: {bad}")
    if any(r.dependant is None for r in found):
        raise AssertionError("A route has no dependant, auth check not possible")
    return found
