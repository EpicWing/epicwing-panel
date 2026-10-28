"""Hilfen zum Anlegen von Testdaten über die API."""


def make_nest(client, headers, name="Games"):
    response = client.post("/api/nests", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def egg_body(nest_id, name="Nginx", **changes):
    body = {
        "nest_id": nest_id,
        "name": name,
        "docker_image": "nginx:1.27-alpine",
        "startup": "nginx -g 'daemon off;'",
        "variables": [
            {"name": "Server name", "env_variable": "SERVER_NAME", "default_value": "My Server"},
            {"name": "Motd", "env_variable": "MOTD"},
        ],
    }
    body.update(changes)
    return body


def make_egg(client, headers, nest_id, name="Nginx", **changes):
    response = client.post("/api/eggs", json=egg_body(nest_id, name, **changes), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def make_allocations(client, headers, node_id, first=25001, last=None, ip="45.142.104.41"):
    body = {"ip": ip, "port_start": first, "port_end": last}
    response = client.post(f"/api/nodes/{node_id}/allocations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return [row["id"] for row in response.json()]
