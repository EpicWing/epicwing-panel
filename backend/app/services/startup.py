"""Platzhalter im Startbefehl, zum Beispiel {{SERVER_MEMORY}} oder {{MAX_PLAYERS}}."""

import re

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")

BUILTIN = {"SERVER_MEMORY", "SERVER_IP", "SERVER_PORT"}
# Schreibweisen älterer Pterodactyl-Eggs.
ALIASES = {
    "server.build.memory": "SERVER_MEMORY",
    "server.build.default.ip": "SERVER_IP",
    "server.build.default.port": "SERVER_PORT",
}


def unknown(startup: str, env_names: list[str]) -> list[str]:
    """Platzhalter, die weder eingebaut noch eine Variable des Eggs sind."""
    known = BUILTIN | set(ALIASES) | set(env_names) | {f"env.{n}" for n in env_names}
    return sorted({m.group(1) for m in _PLACEHOLDER.finditer(startup)} - known)


def render(
    startup: str, variables: dict[str, str], memory_mb: int, ip: str | None, port: int | None
) -> str:
    """Setzt die Werte ein. Nur eine Vorschau: Der Agent darf diesen Text nie ungeprüft
    durch eine Shell schicken, denn die Werte stammen von Nutzern."""
    values = dict(variables)
    values["SERVER_MEMORY"] = str(memory_mb)
    if ip is not None:
        values["SERVER_IP"] = ip
    if port is not None:
        values["SERVER_PORT"] = str(port)

    def replace(match: re.Match[str]) -> str:
        key = ALIASES.get(match.group(1), match.group(1))
        if key.startswith("env."):
            key = key[4:]
        return values.get(key, match.group(0))

    return _PLACEHOLDER.sub(replace, startup)
