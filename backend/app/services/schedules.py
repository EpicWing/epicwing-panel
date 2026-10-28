"""Cron-Ausdrücke für Zeitpläne prüfen und den nächsten Lauf berechnen (Zeitzone des Panels)."""

import os
import re
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

ACTIONS = ("power", "command", "backup")
POWER_ACTIONS = ("start", "stop", "restart", "kill")

# Nur Ziffern, *, /, Komma und Bindestrich. Keine Namen wie "mon", keine Leerzeichen.
_ALLOWED = re.compile(r"^[0-9*/,-]{1,32}$")


def build_expression(
    minute: str, hour: str, day_of_month: str, month: str, day_of_week: str
) -> str:
    """Setzt die fünf Felder zusammen. Wirft ValueError bei ungültigen Werten."""
    parts = [part.strip() for part in (minute, hour, day_of_month, month, day_of_week)]
    for part in parts:
        if not _ALLOWED.match(part):
            raise ValueError("Cron fields may only contain digits and the characters * / , -")
    expression = " ".join(parts)
    if not croniter.is_valid(expression):
        raise ValueError("This is not a valid cron expression")
    return expression


def next_run(expression: str, after: datetime | None = None) -> datetime:
    """Nächster Lauf nach dem Zeitpunkt after (Standard: jetzt). Die Cron-Felder gelten in der
    Zeitzone des Panels, das Ergebnis kommt in UTC."""
    base = after or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    local = base.astimezone(zone())
    return croniter(expression, local).get_next(datetime).astimezone(UTC)


def zone_name() -> str:
    """Zeitzone des Panels. Standard Europe/Berlin, änderbar mit EPICWING_TIMEZONE."""
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
