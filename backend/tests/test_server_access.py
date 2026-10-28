import importlib
import re
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, update
from starlette.websockets import WebSocketDisconnect

from app.models import EggVariable, Role, RolePermission, User, UserRole
from app.models.server import ServerMember, ServerMemberPermission
from app.security.passwords import hash_password
from app.security.server_access import ALL_SERVER_PERMISSIONS, ServerPermission
from tests.conftest import TEST_PASSWORD
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login
from tests.test_server_power import FakeBroker

P = ServerPermission


def _user(db_session, email):
    account = User(email=email, password_hash=hash_password(TEST_PASSWORD), is_admin=False)
    db_session.add(account)
    db_session.commit()
    return account


def _grant(db_session, world, account, *permissions):
    member = ServerMember(server_id=uuid.UUID(world.server_id), user_id=account.id)
    db_session.add(member)
    db_session.flush()
    for permission in permissions:
        db_session.add(ServerMemberPermission(member_id=member.id, permission=permission.value))
    db_session.commit()
    return member


def _add(db_session, member, permission):
    db_session.add(ServerMemberPermission(member_id=member.id, permission=permission.value))
    db_session.commit()


@pytest.fixture
def world(client, user, db_session, monkeypatch):
    broker = FakeBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", broker)
    owner = _user(db_session, "owner@example.test")
    member = _user(db_session, "member@example.test")
    stranger = _user(db_session, "stranger@example.test")
    headers = _login(client, user)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run {{SERVER_PORT}}")
    allocations = make_allocations(client, headers, node_id, 25001, 25001)
    body = {
        "name": "Game 1",
        "owner_id": str(owner.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
    }
    created = client.post("/api/servers", json=body, headers=headers)
    assert created.status_code == 201, created.text
    server_id = created.json()["id"]
    return SimpleNamespace(
        admin=user,
        owner=owner,
        member=member,
        stranger=stranger,
        server_id=server_id,
        url=f"/api/servers/{server_id}",
        broker=broker,
    )


# Pfad, Methode und Body für jeden Endpunkt mit server_id, der ein Recht braucht.
DENIED_FOR_VIEWERS = [
    ("PATCH", "", {"name": "x"}),
    ("POST", "/install", None),
    ("POST", "/power", {"action": "start"}),
    ("POST", "/console/ticket", {}),
    ("GET", "/startup", None),
    ("GET", "/files?path=/", None),
    ("PUT", "/files/content", {}),
    ("POST", "/files/folder", {}),
    ("POST", "/files/rename", {}),
    ("POST", "/files/delete", {}),
    ("POST", "/files/decompress", {}),
    ("POST", "/files/upload-ticket", {}),
    ("POST", "/files/download-ticket", {}),
    ("GET", "/allocations", None),
    ("GET", "/allocations/free", None),
    ("POST", "/allocations", {}),
    ("DELETE", "/allocations/00000000-0000-4000-8000-000000000001", None),
    ("PUT", "/allocations/00000000-0000-4000-8000-000000000001/primary", None),
    ("GET", "/files/content?path=/x", None),
    ("GET", "/files/download?path=/x", None),
    ("GET", "/access", None),
    ("POST", "/access", {}),
    ("PUT", "/access/00000000-0000-4000-8000-000000000002", {}),
    ("DELETE", "/access/00000000-0000-4000-8000-000000000002", None),
    ("GET", "/access/candidates", None),
    ("GET", "/backups", None),
    ("POST", "/backups", {}),
    ("GET", "/backups/00000000-0000-4000-8000-000000000003", None),
    ("PATCH", "/backups/00000000-0000-4000-8000-000000000003", {"is_locked": True}),
    ("DELETE", "/backups/00000000-0000-4000-8000-000000000003", None),
    ("POST", "/backups/00000000-0000-4000-8000-000000000003/restore", None),
    ("GET", "/backups/00000000-0000-4000-8000-000000000003/restore", None),
    ("GET", "/backups/00000000-0000-4000-8000-000000000003/download", None),
    (
        "POST",
        "/backups/00000000-0000-4000-8000-000000000003/transfer",
        {"target_server_id": "00000000-0000-4000-8000-000000000004"},
    ),
    ("GET", "/activity", None),
    ("GET", "/activity/export", None),
    ("GET", "/schedules", None),
    ("POST", "/schedules", {"name": "x"}),
    ("GET", "/schedules/00000000-0000-4000-8000-000000000005", None),
    ("PATCH", "/schedules/00000000-0000-4000-8000-000000000005", {"enabled": False}),
    ("DELETE", "/schedules/00000000-0000-4000-8000-000000000005", None),
    (
        "POST",
        "/schedules/00000000-0000-4000-8000-000000000005/tasks",
        {"action": "power", "payload": "start"},
    ),
    (
        "DELETE",
        "/schedules/00000000-0000-4000-8000-000000000005/tasks/00000000-0000-4000-8000-000000000006",
        None,
    ),
    ("POST", "/schedules/00000000-0000-4000-8000-000000000005/execute", None),
    ("GET", "/databases", None),
    ("POST", "/databases", {"name": "x"}),
    ("POST", "/databases/00000000-0000-4000-8000-000000000007/rotate", None),
    ("DELETE", "/databases/00000000-0000-4000-8000-000000000007", None),
]

# Routen mit Server-ID, die absichtlich nicht in der Matrix stehen.
# Die Konsole per WebSocket steht nicht im OpenAPI-Schema, ihre Rechte prüfen die Ticket-Tests.
NOT_IN_MATRIX = {
    ("GET", "/"),  # Ansicht: server.view reicht
    ("GET", "/ddos"),  # Ansicht: server.view reicht, nur Lesen
    ("DELETE", "/"),  # nur Admin, siehe test_owner_cannot_create_or_delete_servers
}
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _shape(path):
    path = path.split("?", 1)[0] or "/"
    return UUID_RE.sub("{}", re.sub(r"\{[^}]+\}", "{}", path))


def test_every_server_route_is_in_the_permission_matrix():
    from app.main import app

    found = set()
    for path, operations in app.openapi()["paths"].items():
        match = re.search(r"/servers/\{[^}]+\}(.*)$", path)
        if not match:
            continue
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                found.add((method.upper(), _shape(match.group(1))))
    covered = {(m, _shape(p)) for m, p, _ in DENIED_FOR_VIEWERS} | NOT_IN_MATRIX
    missing = sorted(found - covered)
    assert not missing, f"Routen ohne Rechte-Test: {missing}"


def test_stranger_cannot_see_or_touch_the_server(client, world):
    headers = _login(client, world.stranger)
    assert client.get("/api/servers", headers=headers).json() == []
    for method, path, body in [("GET", "", None), *DENIED_FOR_VIEWERS]:
        response = client.request(method, world.url + path, json=body, headers=headers)
        assert response.status_code == 404, (method, path, response.status_code)


def test_unknown_server_is_404_even_for_an_admin(client, world):
    headers = _login(client, world.admin)
    assert client.get(f"/api/servers/{uuid.uuid4()}", headers=headers).status_code == 404


def test_owner_has_every_server_permission(client, world):
    headers = _login(client, world.owner)
    listed = client.get("/api/servers", headers=headers).json()
    assert [s["id"] for s in listed] == [world.server_id]
    detail = client.get(world.url, headers=headers)
    assert detail.status_code == 200
    assert set(detail.json()["permissions"]) == ALL_SERVER_PERMISSIONS


def test_admin_sees_every_server_with_every_permission(client, world):
    headers = _login(client, world.admin)
    assert [s["id"] for s in client.get("/api/servers", headers=headers).json()] == [
        world.server_id
    ]
    detail = client.get(world.url, headers=headers).json()
    assert set(detail["permissions"]) == ALL_SERVER_PERMISSIONS


def test_global_project_role_keeps_full_access(client, db_session, world):
    ops = _user(db_session, "ops@example.test")
    role = Role(name="ops", scope="global")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission="projects.manage"))
    db_session.add(UserRole(user_id=ops.id, role_id=role.id))
    db_session.commit()
    headers = _login(client, ops)
    assert [s["id"] for s in client.get("/api/servers", headers=headers).json()] == [
        world.server_id
    ]
    detail = client.get(world.url, headers=headers).json()
    assert set(detail["permissions"]) == ALL_SERVER_PERMISSIONS


def test_member_without_rights_can_only_view(client, db_session, world):
    _grant(db_session, world, world.member)
    headers = _login(client, world.member)
    listed = client.get("/api/servers", headers=headers).json()
    assert [s["id"] for s in listed] == [world.server_id]
    detail = client.get(world.url, headers=headers)
    assert detail.status_code == 200
    assert detail.json()["permissions"] == ["server.view"]
    for method, path, body in DENIED_FOR_VIEWERS:
        response = client.request(method, world.url + path, json=body, headers=headers)
        assert response.status_code == 403, (method, path, response.status_code)


def test_unknown_stored_permissions_grant_nothing(client, db_session, world):
    member = _grant(db_session, world, world.member)
    db_session.add(ServerMemberPermission(member_id=member.id, permission="power.everything"))
    db_session.commit()
    headers = _login(client, world.member)
    assert client.get(world.url, headers=headers).json()["permissions"] == ["server.view"]


def test_owner_cannot_create_or_delete_servers(client, world):
    headers = _login(client, world.owner)
    assert client.post("/api/servers", json={}, headers=headers).status_code == 403
    assert client.delete(world.url, headers=headers).status_code == 403


def test_power_rights_are_checked_per_action(client, db_session, world):
    admin_headers = _login(client, world.admin)
    assert client.post(world.url + "/install", headers=admin_headers).status_code == 200
    member = _grant(db_session, world, world.member, P.POWER_START)
    headers = _login(client, world.member)

    def power(action):
        return client.post(world.url + "/power", json={"action": action}, headers=headers)

    assert power("start").status_code == 200
    assert power("stop").status_code == 403
    assert power("restart").status_code == 403
    assert power("kill").status_code == 403
    _add(db_session, member, P.POWER_STOP)
    assert power("kill").status_code == 200


def test_install_needs_the_reinstall_right(client, db_session, world):
    member = _grant(db_session, world, world.member, P.SETTINGS_UPDATE)
    headers = _login(client, world.member)
    assert client.post(world.url + "/install", headers=headers).status_code == 403
    _add(db_session, member, P.SETTINGS_REINSTALL)
    assert client.post(world.url + "/install", headers=headers).status_code == 200


def _reached_the_endpoint(client, method, url, **kwargs):
    # Der Fake-Agent liefert keine Dateidaten. Ein Fehler nach der Rechteprüfung zählt als
    # "durchgelassen", entscheidend ist hier nur, dass es weder 403 noch 404 gab.
    try:
        return client.request(method, url, **kwargs).status_code not in (403, 404)
    except Exception:
        return True


def test_file_rights_split_read_and_write(client, db_session, world):
    member = _grant(db_session, world, world.member, P.FILES_READ)
    headers = _login(client, world.member)
    assert _reached_the_endpoint(client, "GET", world.url + "/files?path=/", headers=headers)
    assert _reached_the_endpoint(
        client, "POST", world.url + "/files/download-ticket", json={"path": "/x"}, headers=headers
    )
    for path in (
        "/files/content",
        "/files/folder",
        "/files/rename",
        "/files/delete",
        "/files/decompress",
        "/files/upload-ticket",
    ):
        method = "PUT" if path.endswith("content") else "POST"
        response = client.request(method, world.url + path, json={}, headers=headers)
        assert response.status_code == 403, path
    db_session.execute(
        delete(ServerMemberPermission).where(ServerMemberPermission.member_id == member.id)
    )
    db_session.commit()
    _add(db_session, member, P.FILES_WRITE)
    assert client.get(world.url + "/files?path=/", headers=headers).status_code == 403
    denied = client.post(world.url + "/files/download-ticket", json={"path": "/x"}, headers=headers)
    assert denied.status_code == 403
    assert _reached_the_endpoint(
        client, "POST", world.url + "/files/upload-ticket", json={"path": "/x"}, headers=headers
    )


def test_console_ticket_needs_console_view(client, db_session, world):
    member = _grant(db_session, world, world.member)
    headers = _login(client, world.member)
    url = world.url + "/console/ticket"
    assert client.post(url, json={}, headers=headers).status_code == 403
    _add(db_session, member, P.CONSOLE_VIEW)
    response = client.post(url, json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["ticket"]


def test_ticket_stops_working_after_the_right_is_revoked(client, db_session, world):
    member = _grant(db_session, world, world.member, P.CONSOLE_VIEW)
    headers = _login(client, world.member)
    ticket = client.post(world.url + "/console/ticket", json={}, headers=headers).json()["ticket"]
    db_session.execute(
        delete(ServerMemberPermission).where(ServerMemberPermission.member_id == member.id)
    )
    db_session.commit()
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"{world.url}/console?ticket={ticket}"),
    ):
        pass


def test_owner_can_edit_settings_but_not_resources(client, world):
    headers = _login(client, world.owner)
    assert client.patch(world.url, json={"name": "Renamed"}, headers=headers).status_code == 200
    for body in (
        {"memory_mb": 2048},
        {"cpus": 2.0},
        {"disk_mb": 9000},
        {"image": "nginx:1.27-alpine"},
        {"startup": "run"},
    ):
        response = client.patch(world.url, json=body, headers=headers)
        assert response.status_code == 403, body
    admin_headers = _login(client, world.admin)
    response = client.patch(world.url, json={"memory_mb": 2048}, headers=admin_headers)
    assert response.status_code == 200


def test_member_update_rights_follow_the_field(client, db_session, world):
    db_session.execute(
        update(EggVariable)
        .where(EggVariable.env_variable == "SERVER_NAME")
        .values(user_editable=True, user_viewable=True)
    )
    db_session.commit()
    db_session.expire_all()
    member = _grant(db_session, world, world.member, P.STARTUP_UPDATE)
    headers = _login(client, world.member)
    assert client.patch(world.url, json={"name": "x"}, headers=headers).status_code == 403
    body = {"variables": {"SERVER_NAME": "Mine"}}
    assert client.patch(world.url, json=body, headers=headers).status_code == 200
    _add(db_session, member, P.SETTINGS_UPDATE)
    assert client.patch(world.url, json={"name": "x"}, headers=headers).status_code == 200


def test_locked_and_hidden_variables_stay_admin_only(client, db_session, world):
    db_session.execute(
        update(EggVariable)
        .where(EggVariable.env_variable == "SERVER_NAME")
        .values(user_editable=True, user_viewable=True)
    )
    db_session.execute(
        update(EggVariable)
        .where(EggVariable.env_variable == "MOTD")
        .values(user_editable=False, user_viewable=False)
    )
    db_session.commit()
    db_session.expire_all()

    admin_headers = _login(client, world.admin)
    body = {"variables": {"MOTD": "secret"}}
    assert client.patch(world.url, json=body, headers=admin_headers).status_code == 200
    assert client.get(world.url, headers=admin_headers).json()["variables"]["MOTD"] == "secret"

    headers = _login(client, world.owner)
    detail = client.get(world.url, headers=headers).json()
    assert "MOTD" not in detail["variables"]
    assert "SERVER_NAME" in detail["variables"]
    startup = client.get(world.url + "/startup", headers=headers).json()
    assert "MOTD" not in [v["env_variable"] for v in startup["variables"]]
    blocked = client.patch(world.url, json={"variables": {"MOTD": "x"}}, headers=headers)
    assert blocked.status_code == 403
    ok = {"variables": {"SERVER_NAME": "Mine"}}
    assert client.patch(world.url, json=ok, headers=headers).status_code == 200


def test_allocation_rights_split_view_and_manage(client, db_session, world):
    member = _grant(db_session, world, world.member, P.ALLOCATIONS_VIEW)
    headers = _login(client, world.member)
    listed = client.get(world.url + "/allocations", headers=headers)
    assert listed.status_code == 200
    assert [a["port"] for a in listed.json()] == [25001]
    assert client.get(world.url + "/allocations/free", headers=headers).status_code == 403
    unknown = {"allocation_id": str(uuid.uuid4())}
    assert client.post(world.url + "/allocations", json=unknown, headers=headers).status_code == 403
    _add(db_session, member, P.ALLOCATIONS_MANAGE)
    assert client.get(world.url + "/allocations/free", headers=headers).status_code == 200
    # 422 statt 403: Das Recht greift, die Allocation gibt es nur nicht.
    assert client.post(world.url + "/allocations", json=unknown, headers=headers).status_code == 422


def test_access_candidates_exclude_owner_members_and_self(client, db_session, world):
    manager = _user(db_session, "manager@example.test")
    _grant(db_session, world, manager, P.ACCESS_MANAGE)
    headers = _login(client, manager)
    response = client.get(world.url + "/access/candidates", headers=headers)
    assert response.status_code == 200, response.text
    emails = {row["email"] for row in response.json()}
    assert "stranger@example.test" in emails
    assert "member@example.test" in emails
    assert "owner@example.test" not in emails
    assert "manager@example.test" not in emails
    found = client.get(world.url + "/access/candidates?q=STRANG", headers=headers).json()
    assert [row["email"] for row in found] == ["stranger@example.test"]
    _grant(db_session, world, world.member)
    again = client.get(world.url + "/access/candidates", headers=headers).json()
    assert "member@example.test" not in {row["email"] for row in again}


def test_backup_view_does_not_allow_changes(client, db_session, world):
    _grant(db_session, world, world.member, P.BACKUPS_VIEW)
    headers = _login(client, world.member)
    backup = "00000000-0000-4000-8000-000000000003"
    assert client.get(world.url + "/backups", headers=headers).status_code == 200
    for method, path, body in [
        ("POST", "/backups", {}),
        ("PATCH", f"/backups/{backup}", {"is_locked": True}),
        ("DELETE", f"/backups/{backup}", None),
        ("POST", f"/backups/{backup}/restore", None),
        ("GET", f"/backups/{backup}/restore", None),
        ("GET", f"/backups/{backup}/download", None),
    ]:
        response = client.request(method, world.url + path, json=body, headers=headers)
        assert response.status_code == 403, (method, path, response.status_code)


def test_backup_limit_is_admin_only(client, db_session, world):
    _grant(db_session, world, world.member, P.SETTINGS_UPDATE)
    headers = _login(client, world.member)
    response = client.patch(world.url, json={"backup_limit": 3}, headers=headers)
    assert response.status_code == 403, response.status_code


def test_backup_limit_admin_can_set_within_range(client, world):
    headers = _login(client, world.admin)
    ok = client.patch(world.url, json={"backup_limit": 3}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["backup_limit"] == 3
    bad = client.patch(world.url, json={"backup_limit": 2000}, headers=headers)
    assert bad.status_code == 422, bad.status_code
