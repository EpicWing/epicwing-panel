"""Placeholders in the start command, for example {{SERVER_MEMORY}} or {{MAX_PLAYERS}}."""

import re

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")

BUILTIN = {"SERVER_MEMORY", "SERVER_IP", "SERVER_PORT"}
# Spellings used by older Pterodactyl eggs.
ALIASES = {
    "server.build.memory": "SERVER_MEMORY",
    "server.build.default.ip": "SERVER_IP",
    "server.build.default.port": "SERVER_PORT",
}


def unknown(startup: str, env_names: list[str]) -> list[str]:
    """Placeholders that are neither built in nor a variable of the egg."""
    known = BUILTIN | set(ALIASES) | set(env_names) | {f"env.{n}" for n in env_names}
    return sorted({m.group(1) for m in _PLACEHOLDER.finditer(startup)} - known)


def render(
    startup: str,
    variables: dict[str, str],
    memory_mb: int,
    ip: str | None,
    port: int | None,
    host_memory_mb: int | None = None,
) -> str:
    """Fills in the values. Only a preview: the agent must never pass this text
    to a shell unchecked, because the values come from users."""
    values = dict(variables)
    values.pop("SERVER_MEMORY", None)
    # With 0 (unlimited) the RAM of the node is used, otherwise -Xmx0M would be left.
    if memory_mb > 0:
        values["SERVER_MEMORY"] = str(memory_mb)
    elif host_memory_mb:
        values["SERVER_MEMORY"] = str(host_memory_mb)
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
