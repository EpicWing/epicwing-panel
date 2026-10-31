"""Creates the bundled eggs (backend/fixtures/eggs) that do not exist yet.

Aufruf: python -m app.seed_eggs
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Egg, EggVariable, Nest
from app.services import eggio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eggs"


def _nest(db: Session, name: str) -> Nest:
    nest = db.scalar(select(Nest).where(Nest.name == name))
    if nest is None:
        fields = {"name": name}
        if "description" in Nest.__table__.columns:
            fields["description"] = ""
        nest = Nest(**fields)
        db.add(nest)
        db.flush()
    return nest


def seed(db: Session) -> list[str]:
    """Returns the names of the newly created eggs (nest/egg)."""
    index = json.loads((FIXTURES / "index.json").read_text())
    added: list[str] = []
    for entry in index:
        data = json.loads((FIXTURES / entry["file"]).read_text())
        fields, config, _warnings = eggio.import_egg(data)
        nest = _nest(db, entry["nest"])
        if db.scalar(select(Egg.id).where(Egg.nest_id == nest.id, Egg.name == fields["name"])):
            continue
        variables = fields.pop("variables")
        egg = Egg(nest_id=nest.id, config=config, **fields)
        db.add(egg)
        db.flush()
        for variable in variables:
            db.add(EggVariable(egg_id=egg.id, **variable))
        added.append(f"{entry['nest']}/{fields['name']}")
    db.commit()
    return added


def main() -> int:
    with Session(get_engine()) as db:
        added = seed(db)
    print("Created: " + ", ".join(added) if added else "No new eggs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
