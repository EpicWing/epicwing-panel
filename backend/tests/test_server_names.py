import uuid

import pytest
from pydantic import ValidationError

from app.schemas.egg import NestCreate
from app.schemas.server import ServerCreate, ServerUpdate


def _create(name: str) -> ServerCreate:
    return ServerCreate(
        name=name,
        owner_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        egg_id=uuid.uuid4(),
        allocation_id=uuid.uuid4(),
    )


@pytest.mark.parametrize("name", ["Discord Bot (SCP:SL Status)", "Bot [prod] #1", "Café Bot"])
def test_server_name_allows_punctuation(name: str) -> None:
    assert _create(name).name == name
    assert ServerUpdate(name=name).name == name


def test_server_name_is_trimmed() -> None:
    assert _create("  Bot  ").name == "Bot"


@pytest.mark.parametrize("name", ["", "   ", "x" * 65, "a\nb", "a\x00b", "a\tb"])
def test_server_name_rejects_bad_values(name: str) -> None:
    with pytest.raises(ValidationError):
        _create(name)


def test_other_names_stay_strict() -> None:
    assert NestCreate(name="Java").name == "Java"
    with pytest.raises(ValidationError):
        NestCreate(name="Bad (name)")
