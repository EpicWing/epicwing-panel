from sqlalchemy import select

from app.models import Egg, EggVariable
from app.seed_eggs import seed


def test_seed_adds_the_bundled_eggs_once(db_session):
    first = seed(db_session)
    assert "Generic/Static Website" in first
    assert seed(db_session) == []
    egg = db_session.scalar(select(Egg).where(Egg.name == "Static Website"))
    assert egg is not None
    assert "{{SERVER_PORT}}" in egg.startup


def test_seeded_unturned_keeps_its_variables(db_session):
    seed(db_session)
    egg = db_session.scalar(select(Egg).where(Egg.name == "Unturned"))
    names = {
        v.env_variable
        for v in db_session.scalars(select(EggVariable).where(EggVariable.egg_id == egg.id))
    }
    assert {"GSLT", "SRV_NAME", "SRV_ID"} <= names
