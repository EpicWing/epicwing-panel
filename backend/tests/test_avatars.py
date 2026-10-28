import uuid

import pytest

PASSWORD = "correct-horse-battery"
EMAIL = "admin@example.test"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
RAW = {"Content-Type": "application/octet-stream"}
URL = "/api/avatars/me"


@pytest.fixture
def headers(client, user):
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _put(client, headers, data):
    return client.put(URL, content=data, headers={**headers, **RAW})


@pytest.mark.parametrize(
    ("data", "content_type"), [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")]
)
def test_upload_and_fetch(client, user, headers, data, content_type):
    assert _put(client, headers, data).status_code == 204
    response = client.get(f"/api/avatars/{user.id}")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == content_type
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_replacing_keeps_a_single_avatar(client, user, headers):
    assert _put(client, headers, PNG).status_code == 204
    assert _put(client, headers, JPEG).status_code == 204
    response = client.get(f"/api/avatars/{user.id}")
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"just text",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<html><script>alert(1)</script></html>",
    ],
)
def test_non_images_are_rejected(client, user, headers, data):
    assert _put(client, headers, data).status_code == 415
    assert client.get(f"/api/avatars/{user.id}").status_code == 404


def test_declared_type_does_not_matter(client, user, headers):
    response = client.put(
        URL, content=b"<svg/>", headers={**headers, "Content-Type": "image/png"}
    )
    assert response.status_code == 415


def test_oversized_image_is_rejected(client, user, headers):
    assert _put(client, headers, PNG + b"\x00" * (1024 * 1024)).status_code == 413
    assert client.get(f"/api/avatars/{user.id}").status_code == 404


def test_delete_removes_the_avatar(client, user, headers):
    _put(client, headers, PNG)
    assert client.delete(URL, headers=headers).status_code == 204
    assert client.get(f"/api/avatars/{user.id}").status_code == 404
    assert client.delete(URL, headers=headers).status_code == 204


def test_etag_gives_304(client, user, headers):
    _put(client, headers, PNG)
    first = client.get(f"/api/avatars/{user.id}")
    etag = first.headers["etag"]
    again = client.get(f"/api/avatars/{user.id}", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""


def test_unknown_user_is_404(client, user, headers):
    assert client.get(f"/api/avatars/{uuid.uuid4()}").status_code == 404


def test_needs_a_login(client, user):
    assert client.get(f"/api/avatars/{user.id}").status_code in (401, 403)
    assert client.put(URL, content=PNG, headers=RAW).status_code in (401, 403)
    assert client.delete(URL).status_code in (401, 403)


def test_write_needs_the_csrf_token(client, user, headers):
    assert client.put(URL, content=PNG, headers=RAW).status_code in (401, 403)
    assert client.delete(URL).status_code in (401, 403)
    assert client.get(f"/api/avatars/{user.id}").status_code == 404
