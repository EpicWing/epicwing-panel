"""Cron-Ausdrücke für Zeitpläne prüfen und den nächsten Lauf berechnen (alles in UTC)."""

import re
from datetime import UTC, datetime

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
    """Nächster Lauf nach dem Zeitpunkt after (Standard: jetzt), mit Zeitzone UTC."""
    base = after or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    return croniter(expression, base).get_next(datetime)
