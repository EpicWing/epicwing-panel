"""Encrypts secret variable values that are still stored as plain text.

Aufruf: python -m app.encrypt_secrets
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import EggVariable, Server, ServerVariable
from app.services import secretvars


def encrypt_plain_values(db: Session) -> int:
    egg_of = dict(db.execute(select(Server.id, Server.egg_id)).all())
    secret_keys = {
        (v.egg_id, v.env_variable)
        for v in db.scalars(select(EggVariable).where(EggVariable.secret.is_(True)))
    }
    changed = 0
    for row in db.scalars(select(ServerVariable)):
        if (egg_of.get(row.server_id), row.env_variable) not in secret_keys:
            continue
        if not row.value or row.value.startswith(secretvars.PREFIX):
            continue
        row.value = secretvars.seal(row.value)
        changed += 1
    db.commit()
    return changed


def main() -> int:
    with Session(get_engine()) as db:
        count = encrypt_plain_values(db)
    print(f"Encrypted {count} value(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
