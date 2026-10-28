from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.api.ssh_keys import MAX_KEYS
from app.models import SshKey, User
from tests.test_api_keys import _bearer, _create, _login


def _pub(comment: str = "laptop") -> str:
    raw = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    )
    return raw.decode() + " " + comment


def _add(client, headers, name="laptop", key=None):
    return client.post(
        "/api/ssh-keys", json={"name": name, "public_key": key or _pub()}, headers=headers
    )


def test_add_list_and_delete(client, credentials):
    headers = _login(client, credentials)
    reply = _add(client, headers)
    assert reply.status_code == 201, reply.text
    created = reply.json()
    assert created["fingerprint"].startswith("SHA256:")
    assert created["key_type"] == "ssh-ed25519"
    assert "public_key" not in created
    assert [row["name"] for row in client.get("/api/ssh-keys").json()] == ["laptop"]
    assert client.delete(f"/api/ssh-keys/{created['id']}", headers=headers).status_code == 204
    assert client.get("/api/ssh-keys").json() == []


def test_comment_is_stripped(client, credentials, db_session):
    headers = _login(client, credentials)
    _add(client, headers, key=_pub("secret-comment"))
    row = db_session.query(SshKey).one()
    assert "secret-comment" not in row.public_key


def test_garbage_is_rejected(client, credentials):
    headers = _login(client, credentials)
    assert _add(client, headers, key="hello").status_code == 422
    assert _add(client, headers, key="ssh-ed25519 !!!notbase64").status_code == 422
    assert _add(client, headers, key="ssh-dss AAAA").status_code == 422


def test_type_mismatch_is_rejected(client, credentials):
    headers = _login(client, credentials)
    swapped = _pub().replace("ssh-ed25519", "ecdsa-sha2-nistp256", 1)
    assert _add(client, headers, key=swapped).status_code == 422


def test_two_keys_in_one_field_are_rejected(client, credentials):
    headers = _login(client, credentials)
    assert _add(client, headers, key=_pub() + "\n" + _pub()).status_code == 422


def test_duplicate_key_is_rejected(client, credentials):
    headers = _login(client, credentials)
    key = _pub()
    assert _add(client, headers, key=key).status_code == 201
    assert _add(client, headers, name="again", key=key).status_code == 409


def test_keys_are_limited_per_user(client, credentials, db_session, user):
    for i in range(MAX_KEYS):
        db_session.add(
            SshKey(
                user_id=user.id,
                name=f"k{i}",
                key_type="ssh-ed25519",
                public_key="x",
                fingerprint=f"SHA256:fake{i}",
            )
        )
    db_session.commit()
    headers = _login(client, credentials)
    assert _add(client, headers).status_code == 409


def test_other_users_keys_are_invisible(client, credentials, db_session):
    other = User(email="other@example.test", password_hash="not-a-real-hash")
    db_session.add(other)
    db_session.commit()
    foreign = SshKey(
        user_id=other.id,
        name="theirs",
        key_type="ssh-ed25519",
        public_key="x",
        fingerprint="SHA256:foreign",
    )
    db_session.add(foreign)
    db_session.commit()
    headers = _login(client, credentials)
    assert client.get("/api/ssh-keys").json() == []
    assert client.delete(f"/api/ssh-keys/{foreign.id}", headers=headers).status_code == 404
    assert db_session.get(SshKey, foreign.id) is not None


def test_needs_a_session(client):
    assert client.get("/api/ssh-keys").status_code == 401
    assert client.post("/api/ssh-keys", json={}).status_code == 401


def test_api_key_cannot_manage_ssh_keys(client, credentials):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    client.cookies.clear()
    assert client.get("/api/ssh-keys", headers=_bearer(token)).status_code == 401
