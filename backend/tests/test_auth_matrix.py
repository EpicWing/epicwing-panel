import re
import uuid

from app.main import app

# Routen, die ohne Login erreichbar sein duerfen: nach dem ersten Durchlauf ergaenzen
PUBLIC: set[tuple[str, str]] = {
    ("GET", "/api/health"),
    ("GET", "/api/panel"),
    ("POST", "/api/agent/enroll"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/2fa"),
    ("GET", "/api/auth/password-reset/available"),
    ("POST", "/api/auth/password-reset/request"),
    ("POST", "/api/auth/password-reset/confirm"),
}

METHODS = {"get", "post", "put", "patch", "delete"}


def _routes():
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.lower() in METHODS:
                yield method.upper(), path


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.UUID(int=1)), path)


def test_routes_need_login(client):
    reachable = []
    routes = sorted(_routes(), key=lambda item: (item[1], item[0]))
    for method, path in routes:
        response = client.request(method, _fill(path), json={} if method != "GET" else None)
        if response.status_code not in (401, 403) and (method, path) not in PUBLIC:
            reachable.append(f"{response.status_code} {method} {path}")
    print(f"\n{len(routes)} Routen geprueft, ohne Login erreichbar:")
    print("\n".join(reachable) or "keine")
    assert not reachable
