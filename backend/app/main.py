from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    agent,
    agent_ws,
    allocations,
    audit,
    auth,
    avatars,
    backups,
    console_ws,
    eggs,
    health,
    nodes,
    panel,
    server_members,
    servers,
    two_factor,
    users,
)
from app.api.admin_mail import router as admin_mail_router
from app.config import get_settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="EpicWing",
        version="0.0.1",
        # API-Doku nur in der Entwicklung öffentlich
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        # Schreibende Requests mit fremdem Origin-Header werden abgelehnt.
        origin = request.headers.get("origin")
        if (
            request.method not in _SAFE_METHODS
            and origin
            and origin not in settings.allowed_origins
        ):
            return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
        return await call_next(request)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(two_factor.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(audit.server_router, prefix="/api")
    app.include_router(nodes.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(agent_ws.router, prefix="/api")
    app.include_router(console_ws.router, prefix="/api")
    app.include_router(eggs.nests_router, prefix="/api")
    app.include_router(eggs.router, prefix="/api")
    app.include_router(allocations.router, prefix="/api")
    app.include_router(servers.router, prefix="/api")
    app.include_router(server_members.router, prefix="/api")
    app.include_router(avatars.router, prefix="/api")
    app.include_router(backups.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(admin_mail_router, prefix="/api")
    app.include_router(panel.router, prefix="/api")
    return app


app = create_app()
