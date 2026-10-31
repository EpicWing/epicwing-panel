import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import UserAvatar
from app.security.sessions import CurrentAuth

router = APIRouter(prefix="/avatars", tags=["avatars"])
DbSession = Annotated[Session, Depends(get_db)]

MAX_BYTES = 1024 * 1024


def _detect(data: bytes) -> str | None:
    """Detects the image type from the file header. The Content-Type from the client does not count.

    The image is not re-encoded (no image library installed). So it is
    served with nosniff and a strict CSP, SVG is not allowed.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _too_large() -> HTTPException:
    return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The image must not exceed 1 MB.")


@router.put("/me", status_code=status.HTTP_204_NO_CONTENT)
async def upload_avatar(request: Request, auth: CurrentAuth, db: DbSession) -> Response:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise _too_large()
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_BYTES:
            raise _too_large()
    data = bytes(buffer)
    content_type = _detect(data)
    if content_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PNG, JPEG and WebP images are allowed."
        )
    digest = hashlib.sha256(data).hexdigest()
    row = db.get(UserAvatar, auth.user.id)
    if row is None:
        db.add(
            UserAvatar(user_id=auth.user.id, content_type=content_type, data=data, sha256=digest)
        )
    else:
        row.content_type = content_type
        row.data = data
        row.sha256 = digest
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(auth: CurrentAuth, db: DbSession) -> Response:
    row = db.get(UserAvatar, auth.user.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{user_id}")
def get_avatar(user_id: uuid.UUID, request: Request, auth: CurrentAuth, db: DbSession) -> Response:
    row = db.get(UserAvatar, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No avatar.")
    etag = f'"{row.sha256}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, no-cache",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=row.data, media_type=row.content_type, headers=headers)
