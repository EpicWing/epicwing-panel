from datetime import UTC, datetime

import pytest

from app.models import PanelSetting
from app.services import s3

PASSWORD = "correct-horse-battery"
URL = "/api/admin/storage"
NOW = datetime(2013, 5, 24, tzinfo=UTC)
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS = {
    "enabled": True,
    "endpoint": "https://s3.amazonaws.com",
    "region": "us-east-1",
    "bucket": "examplebucket",
    "access_key": "AKIAIOSFODNN7EXAMPLE",
    "secret_key": SECRET,
    "path_style": False,
}


@pytest.fixture
def headers(client, user):
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_presigned_url_matches_the_aws_example():
    # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
    url = s3.presign(s3.S3Config(**AWS), "GET", "test.txt", 86400, now=NOW)
    assert url == (
        "https://examplebucket.s3.amazonaws.com/test.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request"
        "&X-Amz-Date=20130524T000000Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host"
        "&X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )


def test_signed_headers_match_the_aws_example():
    # https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html
    url, headers = s3.sign_request(
        s3.S3Config(**AWS), "GET", "test.txt", headers={"Range": "bytes=0-9"}, now=NOW
    )
    assert url == "https://examplebucket.s3.amazonaws.com/test.txt"
    assert headers["authorization"].endswith(
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    assert "host" not in headers


def test_path_style_and_object_keys():
    config = s3.S3Config(**{**AWS, "path_style": True, "endpoint": "https://r2.example.com/"})
    url = s3.presign(config, "PUT", "a b/c.tar.gz", 60, {"partNumber": "1"}, now=NOW)
    assert url.startswith("https://r2.example.com/examplebucket/a%20b/c.tar.gz?")
    assert "partNumber=1&" in url
    config.prefix = "/epicwing/"
    assert s3.object_key(config, "backups", "x.tar.gz") == "epicwing/backups/x.tar.gz"


def test_settings_keep_the_secret_encrypted(client, headers, db_session):
    response = client.put(URL, json=AWS, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ready"] is True and data["secret_key_set"] is True
    assert "secret_key" not in data
    assert db_session.get(PanelSetting, "s3.secret_key").value != SECRET

    again = client.put(URL, json={**AWS, "secret_key": None}, headers=headers).json()
    assert again["secret_key_set"] is True
    assert s3.load_config(db_session).secret_key == SECRET


@pytest.mark.parametrize(
    "change",
    [
        {"bucket": ""},
        {"endpoint": "https://s3.example.com/some/path"},
        {"prefix": "../escape"},
        {"bucket": "Bad_Bucket"},
    ],
)
def test_settings_reject_bad_values(client, headers, change):
    response = client.put(URL, json={**AWS, **change}, headers=headers)
    assert response.status_code == 422


def test_connection_test_reports_the_error(client, headers, monkeypatch):
    def fail(config):
        raise s3.S3Error("AccessDenied: no")

    monkeypatch.setattr(s3, "check", fail)
    response = client.post(URL + "/test", headers=headers)
    assert response.json() == {"ok": False, "detail": "AccessDenied: no"}


def test_storage_settings_need_a_login(client):
    assert client.get(URL).status_code in (401, 403)
