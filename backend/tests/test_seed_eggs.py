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


def test_seeded_paper_forks_ship_install_scripts_and_variables(db_session):
    seed(db_session)
    stream = db_session.scalar(select(Egg).where(Egg.name == "PaperStream"))
    proxy = db_session.scalar(select(Egg).where(Egg.name == "PaperProxy"))
    assert stream is not None and proxy is not None
    assert "releases" in stream.install_script and "paperstream-start.sh" in stream.install_script
    assert "{{SERVER_PORT}}" in proxy.startup
    names = {
        v.env_variable
        for v in db_session.scalars(select(EggVariable).where(EggVariable.egg_id == stream.id))
    }
    assert {"MINECRAFT_VERSION", "PAPERSTREAM_BUILD", "SERVER_JARFILE"} <= names
