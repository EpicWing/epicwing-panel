import pytest
from sqlalchemy import select

from app.models import AuditLog, User
from app.security.passwords import hash_password

PASSWORD = "correct-horse-battery"
PANEL = "/api/panel"
SETTINGS = "/api/admin/settings"
DEFAULTS = {
    "name": "EpicWing",
    "discord_url": "",
    "docs_url": "",
    "github_url": "",
    "support_url": "",
}


def _login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def headers(client, user):
    return _login(client, user.email)


def _audit_actions(db_session):
    db_session.expire_all()
    return list(db_session.scalars(select(AuditLog.action)))


def test_panel_name_is_public(client):
    assert client.get(PANEL).json() == {"name": "EpicWing"}


def test_settings_need_a_login(client):
    assert client.get(SETTINGS).status_code == 401
    assert client.put(SETTINGS, json=DEFAULTS).status_code == 401


def test_settings_are_admin_only(client, db_session):
    account = User(email="user@example.test", password_hash=hash_password(PASSWORD))
    db_session.add(account)
    db_session.commit()
    headers = _login(client, account.email)
    assert client.get(SETTINGS).status_code == 403
    assert client.put(SETTINGS, json=DEFAULTS, headers=headers).status_code == 403


def test_defaults(client, user, headers):
    assert client.get(SETTINGS).json() == DEFAULTS


def test_update_roundtrip(client, user, headers, db_session):
    body = {
        "name": "  Epic Hosting ",
        "discord_url": "https://discord.gg/example",
        "github_url": "https://github.com/example/repo",
    }
    response = client.put(SETTINGS, json=body, headers=headers)
    assert response.status_code == 200, response.text
    expected = {
        **DEFAULTS,
        "name": "Epic Hosting",
        "discord_url": "https://discord.gg/example",
        "github_url": "https://github.com/example/repo",
    }
    assert response.json() == expected
    assert client.get(SETTINGS).json() == expected
    assert client.get(PANEL).json() == {"name": "Epic Hosting"}

    entry = db_session.scalar(select(AuditLog).where(AuditLog.action == "panel.settings.update"))
    assert entry.actor_id == user.id
    assert entry.details == {"changed": ["name", "discord_url", "github_url"]}


def test_saving_unchanged_values_writes_no_audit_entry(client, user, headers, db_session):
    assert client.put(SETTINGS, json=DEFAULTS, headers=headers).status_code == 200
    assert "panel.settings.update" not in _audit_actions(db_session)


def test_links_can_be_cleared(client, user, headers):
    link = {"name": "EpicWing", "discord_url": "https://discord.gg/example"}
    assert client.put(SETTINGS, json=link, headers=headers).status_code == 200
    assert client.put(SETTINGS, json={"name": "EpicWing"}, headers=headers).status_code == 200
    assert client.get(SETTINGS).json() == DEFAULTS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 41),
        ("name", "Epic\nWing"),
        ("discord_url", "javascript:alert(1)"),
        ("discord_url", "ftp://files.example.test"),
        ("docs_url", "https://"),
        ("docs_url", "example.test/docs"),
        ("github_url", "https://exa mple.test"),
        ("support_url", "https://example.test/" + "a" * 300),
    ],
)
def test_bad_values_are_rejected(client, user, headers, field, value):
    body = {"name": "EpicWing", field: value}
    assert client.put(SETTINGS, json=body, headers=headers).status_code == 422
    assert client.get(SETTINGS).json() == DEFAULTS


def test_unknown_fields_are_rejected(client, user, headers):
    body = {"name": "EpicWing", "admin": True}
    assert client.put(SETTINGS, json=body, headers=headers).status_code == 422


def test_write_needs_the_csrf_token(client, user, headers):
    assert client.put(SETTINGS, json=DEFAULTS).status_code == 403
