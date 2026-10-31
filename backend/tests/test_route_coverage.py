from app.main import app
from tests.helpers import collect_routes


def test_collector_sees_every_documented_route():
    """OpenAPI is built independently of the collector and serves as a cross-check."""
    documented = {
        (path, method.upper()) for path, item in app.openapi()["paths"].items() for method in item
    }
    collected = {
        (route.path, method)
        for route in collect_routes(app)
        if not route.websocket
        for method in route.methods
    }
    assert documented, "OpenAPI liefert keine Pfade"
    assert collected == documented, (
        f"Missed by the collector: {sorted(documented - collected)}; "
        f"nicht in OpenAPI: {sorted(collected - documented)}"
    )
