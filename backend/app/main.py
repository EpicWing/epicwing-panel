from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import audit, auth, health, nodes, users
from app.config import get_settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Forge",
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
            return JSONResponse({"detail": "Origin nicht erlaubt."}, status_code=403)
        return await call_next(request)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(nodes.router, prefix="/api")
    return app


app = create_app()
