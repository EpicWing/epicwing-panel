from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    # Prüfen, ob die Datenbank erreichbar ist.
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
