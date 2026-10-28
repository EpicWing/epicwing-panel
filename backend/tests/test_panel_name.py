import pytest

BLOCKED = (401, 403, 404, 405)


def test_panel_name_is_public_and_fixed(client):
    response = client.get("/api/panel")
    assert response.status_code == 200
    assert response.json() == {"name": "EpicWing"}


@pytest.mark.parametrize("method", ["GET", "PUT", "POST", "PATCH", "DELETE"])
def test_settings_endpoint_is_gone(client, method):
    response = client.request(method, "/api/admin/settings", json={"name": "x"})
    assert response.status_code in BLOCKED


@pytest.mark.parametrize("method", ["PUT", "POST", "PATCH", "DELETE"])
def test_panel_name_cannot_be_written(client, method):
    response = client.request(method, "/api/panel", json={"name": "x"})
    assert response.status_code in BLOCKED
    assert client.get("/api/panel").json() == {"name": "EpicWing"}
