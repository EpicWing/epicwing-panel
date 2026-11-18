from tests.test_nodes_detail import _login


def test_user_can_set_and_clear_a_display_name(client, user):
    headers = _login(client, user)
    named = client.put("/api/auth/me/name", json={"display_name": "  Leif \n W "}, headers=headers)
    assert named.status_code == 200, named.text
    assert named.json()["display_name"] == "Leif W"
    assert client.get("/api/auth/me").json()["user"]["display_name"] == "Leif W"

    cleared = client.put("/api/auth/me/name", json={"display_name": "   "}, headers=headers)
    assert cleared.json()["display_name"] is None
    too_long = client.put("/api/auth/me/name", json={"display_name": "x" * 49}, headers=headers)
    assert too_long.status_code == 422


def test_name_needs_a_login(client):
    assert client.put("/api/auth/me/name", json={"display_name": "x"}).status_code in (401, 403)
