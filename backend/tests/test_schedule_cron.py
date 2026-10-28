from datetime import UTC, datetime

import pytest

from app.db import Base
from app.models import Schedule, ScheduleTask  # noqa: F401
from app.services.schedules import build_expression, next_run


def test_valid_expressions():
    assert build_expression("0", "4", "*", "*", "*") == "0 4 * * *"
    assert build_expression("*/5", "*", "*", "*", "1-5") == "*/5 * * * 1-5"
    assert build_expression(" 0 ", "4,16", "*", "*", "*") == "0 4,16 * * *"


@pytest.mark.parametrize(
    "fields",
    [
        ("60", "*", "*", "*", "*"),
        ("*", "25", "*", "*", "*"),
        ("*", "*", "32", "*", "*"),
        ("*", "*", "*", "13", "*"),
        ("a", "*", "*", "*", "*"),
        ("*", "*", "*", "*", "mon"),
        ("1 2", "*", "*", "*", "*"),
        ("", "*", "*", "*", "*"),
        ("*;ls", "*", "*", "*", "*"),
    ],
)
def test_invalid_expressions(fields):
    with pytest.raises(ValueError):
        build_expression(*fields)


def test_next_run_daily():
    after = datetime(2026, 10, 18, 4, 0, tzinfo=UTC)
    assert next_run("0 4 * * *", after) == datetime(2026, 10, 19, 4, 0, tzinfo=UTC)
    before = datetime(2026, 10, 18, 3, 59, tzinfo=UTC)
    assert next_run("0 4 * * *", before) == datetime(2026, 10, 18, 4, 0, tzinfo=UTC)


def test_next_run_every_five_minutes():
    after = datetime(2026, 10, 18, 12, 2, tzinfo=UTC)
    assert next_run("*/5 * * * *", after) == datetime(2026, 10, 18, 12, 5, tzinfo=UTC)


def test_next_run_accepts_naive_datetime_as_utc():
    result = next_run("0 4 * * *", datetime(2026, 10, 18, 3, 0))
    assert result == datetime(2026, 10, 18, 4, 0, tzinfo=UTC)


def test_tables_are_registered():
    assert {"schedules", "schedule_tasks"} <= set(Base.metadata.tables)
    columns = set(Base.metadata.tables["schedule_tasks"].columns.keys())
    assert {"sequence", "action", "payload", "time_offset", "continue_on_failure"} <= columns
