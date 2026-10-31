"""Check cron expressions for schedules and compute the next run (time zone of the panel)."""

import os
import re
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

ACTIONS = ("power", "command", "backup")
POWER_ACTIONS = ("start", "stop", "restart", "kill")

# Only digits, *, /, comma and dash. No names like "mon", no spaces.
_ALLOWED = re.compile(r"^[0-9*/,-]{1,32}$")


def build_expression(
    minute: str, hour: str, day_of_month: str, month: str, day_of_week: str
) -> str:
    """Puts the five fields together. Raises ValueError for invalid values."""
    parts = [part.strip() for part in (minute, hour, day_of_month, month, day_of_week)]
    for part in parts:
        if not _ALLOWED.match(part):
            raise ValueError("Cron fields may only contain digits and the characters * / , -")
    expression = " ".join(parts)
    if not croniter.is_valid(expression):
        raise ValueError("This is not a valid cron expression")
    return expression


def next_run(expression: str, after: datetime | None = None) -> datetime:
    """Next run after the time after (default: now). The cron fields apply in the
    time zone of the panel, the result comes in UTC."""
    base = after or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    local = base.astimezone(zone())
    return croniter(expression, local).get_next(datetime).astimezone(UTC)


def zone_name() -> str:
    """Time zone of the panel. Default Europe/Berlin, can be changed with EPICWING_TIMEZONE."""
    name = os.environ.get("EPICWING_TIMEZONE", "Europe/Berlin")
    if name == "UTC":
        return name
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return name


def zone() -> tzinfo:
    name = zone_name()
    return UTC if name == "UTC" else ZoneInfo(name)
