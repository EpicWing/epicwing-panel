"""S3-compatible storage for backups (AWS, Backblaze B2, Cloudflare R2, Hetzner, Wasabi, MinIO).

The panel keeps the keys. Nodes only get presigned URLs that expire after a while.
Requests are signed with AWS Signature Version 4, without an extra library.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PanelSetting
from app.security.vault import decrypt_text, encrypt_text

PREFIX = "s3."
VAULT_PURPOSE = "s3-storage"
FIELDS = (
    "enabled",
    "endpoint",
    "region",
    "bucket",
    "prefix",
    "access_key",
    "secret_key",
    "path_style",
    "keep_local",
)
SECRET_FIELDS = frozenset({"secret_key"})
UNSIGNED = "UNSIGNED-PAYLOAD"
TIMEOUT = 30.0
MAX_PRESIGN_SECONDS = 7 * 24 * 3600


class S3Error(Exception):
    pass


@dataclass
class S3Config:
    enabled: bool = False
    endpoint: str = ""
    region: str = "auto"
    bucket: str = ""
    prefix: str = "epicwing"
    access_key: str = ""
    secret_key: str = ""
    path_style: bool = True
    keep_local: bool = False

    @property
    def ready(self) -> bool:
        return self.enabled and all((self.endpoint, self.bucket, self.access_key, self.secret_key))


def load_config(db: Session) -> S3Config:
    rows = {
        row.key[len(PREFIX) :]: row.value
        for row in db.scalars(select(PanelSetting).where(PanelSetting.key.like(PREFIX + "%")))
    }
    config = S3Config()
    for name in FIELDS:
        if name not in rows:
            continue
        value = rows[name]
        if name in SECRET_FIELDS and value:
            value = decrypt_text(value, VAULT_PURPOSE) or ""
        if isinstance(getattr(config, name), bool):
            setattr(config, name, value == "1")
        else:
            setattr(config, name, value)
    return config


def save_config(db: Session, values: dict[str, object]) -> None:
    """Saves the settings. Secrets are encrypted, None leaves a value unchanged."""
    for name, value in values.items():
        if name not in FIELDS or value is None:
            continue
        text = ("1" if value else "0") if isinstance(value, bool) else str(value)
        if name in SECRET_FIELDS and text:
            text = encrypt_text(text, VAULT_PURPOSE)
        row = db.get(PanelSetting, PREFIX + name)
        if row is None:
            db.add(PanelSetting(key=PREFIX + name, value=text))
        else:
            row.value = text
    db.commit()


def object_key(config: S3Config, *parts: str) -> str:
    return "/".join(p.strip("/") for p in (config.prefix, *parts) if p.strip("/"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, day: str, region: str) -> bytes:
    key = _hmac(("AWS4" + secret).encode(), day)
    key = _hmac(key, region)
    key = _hmac(key, "s3")
    return _hmac(key, "aws4_request")


def _quote(value: str) -> str:
    return quote(value, safe="-_.~")


def _query(params: dict[str, str]) -> str:
    return "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(params.items()))


def _target(config: S3Config, key: str) -> tuple[str, str, str]:
    """Returns (url without query, host, canonical path)."""
    parts = urlsplit(config.endpoint.strip().rstrip("/"))
    scheme = parts.scheme or "https"
    host = parts.netloc
    path = "/" + quote(key, safe="/-_.~") if key else "/"
    if config.path_style:
        path = "/" + _quote(config.bucket) + (path if key else "")
    else:
        host = f"{config.bucket}.{host}"
    return f"{scheme}://{host}{path}", host, path


def _stamp(now: datetime | None) -> tuple[str, str]:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    return amz_date, amz_date[:8]


def _sign(config: S3Config, amz_date: str, day: str, canonical: str) -> tuple[str, str]:
    scope = f"{day}/{config.region}/s3/aws4_request"
    to_sign = "\n".join(("AWS4-HMAC-SHA256", amz_date, scope, _sha256(canonical.encode())))
    key = _signing_key(config.secret_key, day, config.region)
    return scope, hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()


def presign(
    config: S3Config,
    method: str,
    key: str,
    expires: int,
    params: dict[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    """A URL that allows exactly this request until it expires. Used by the nodes."""
    amz_date, day = _stamp(now)
    url, host, path = _target(config, key)
    query = dict(params or {})
    query.update(
        {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{config.access_key}/{day}/{config.region}/s3/aws4_request",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(max(1, min(expires, MAX_PRESIGN_SECONDS))),
            "X-Amz-SignedHeaders": "host",
        }
    )
    canonical = "\n".join((method, path, _query(query), f"host:{host}\n", "host", UNSIGNED))
    _scope, signature = _sign(config, amz_date, day, canonical)
    return f"{url}?{_query(query)}&X-Amz-Signature={signature}"


def sign_request(
    config: S3Config,
    method: str,
    key: str,
    params: dict[str, str] | None = None,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """Returns the URL and the headers of a request that the panel sends itself."""
    amz_date, day = _stamp(now)
    url, host, path = _target(config, key)
    payload = _sha256(body)
    signed = {k.lower(): " ".join(v.split()) for k, v in (headers or {}).items()}
    signed.update({"host": host, "x-amz-content-sha256": payload, "x-amz-date": amz_date})
    names = sorted(signed)
    canonical = "\n".join(
        (
            method,
            path,
            _query(params or {}),
            "".join(f"{n}:{signed[n]}\n" for n in names),
            ";".join(names),
            payload,
        )
    )
    scope, signature = _sign(config, amz_date, day, canonical)
    signed["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={config.access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    del signed["host"]
    query = _query(params or {})
    return (f"{url}?{query}" if query else url), signed


def _tag(xml: str, name: str) -> str | None:
    found = re.search(rf"<{name}>(.*?)</{name}>", xml, re.DOTALL)
    return unescape(found.group(1)) if found else None


def _request(
    config: S3Config,
    method: str,
    key: str,
    params: dict[str, str] | None = None,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    url, signed = sign_request(config, method, key, params, body, headers)
    try:
        response = httpx.request(method, url, headers=signed, content=body, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise S3Error(f"The storage is not reachable: {exc}") from None
    text = response.text if response.content else ""
    # S3 can answer 200 and still report an error in the body (CompleteMultipartUpload).
    if response.status_code >= 300 or "<Error>" in text:
        code = _tag(text, "Code") or f"HTTP {response.status_code}"
        message = _tag(text, "Message") or ""
        raise S3Error(f"{code}: {message}".rstrip(": "))
    return response


def put_object(config: S3Config, key: str, body: bytes) -> None:
    _request(config, "PUT", key, body=body)


def delete_object(config: S3Config, key: str) -> None:
    _request(config, "DELETE", key)


def create_multipart(config: S3Config, key: str) -> str:
    response = _request(config, "POST", key, params={"uploads": ""})
    upload_id = _tag(response.text, "UploadId")
    if not upload_id:
        raise S3Error("The storage did not return an upload id.")
    return upload_id


def presign_part(config: S3Config, key: str, upload_id: str, number: int, expires: int) -> str:
    params = {"partNumber": str(number), "uploadId": upload_id}
    return presign(config, "PUT", key, expires, params)


def complete_multipart(config: S3Config, key: str, upload_id: str, etags: list[str]) -> None:
    parts = "".join(
        f"<Part><PartNumber>{i}</PartNumber><ETag>{tag}</ETag></Part>"
        for i, tag in enumerate(etags, start=1)
    )
    body = f"<CompleteMultipartUpload>{parts}</CompleteMultipartUpload>".encode()
    _request(
        config,
        "POST",
        key,
        params={"uploadId": upload_id},
        body=body,
        headers={"content-type": "application/xml"},
    )


def abort_multipart(config: S3Config, key: str, upload_id: str) -> None:
    _request(config, "DELETE", key, params={"uploadId": upload_id})


def presign_get(config: S3Config, key: str, expires: int, filename: str | None = None) -> str:
    params = {}
    if filename:
        params["response-content-disposition"] = f'attachment; filename="{filename}"'
    return presign(config, "GET", key, expires, params)


def check(config: S3Config) -> str:
    """Uploads, reads through a presigned URL and deletes a small test object."""
    if not config.ready:
        raise S3Error("Fill in endpoint, bucket, access key and secret key, and turn it on.")
    key = object_key(config, ".epicwing-test", secrets.token_hex(8))
    body = b"EpicWing storage test"
    put_object(config, key, body)
    try:
        try:
            response = httpx.get(presign_get(config, key, 120), timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            raise S3Error(f"The presigned download failed: {exc}") from None
        if response.status_code != 200 or response.content != body:
            raise S3Error(
                f"Upload works, but the presigned download answered HTTP {response.status_code}."
            )
    finally:
        delete_object(config, key)
    return "Upload, presigned download and delete work."
