"""Container-Spezifikation eines Servers, so wie der Node-Agent sie erwartet."""

import uuid
from typing import Any

# Diese Namen setzt das Panel selbst, eine Egg-Variable darf sie nicht überschreiben.
RESERVED = ("STARTUP", "SERVER_MEMORY", "SERVER_IP", "SERVER_PORT")


def container_name(server_id: uuid.UUID) -> str:
    """Name des Containers und des Datenverzeichnisses auf der Node."""
    return str(server_id)


def build_spec(
    server: Any,
    allocations: list[Any],
    variables: dict[str, str],
    host_memory_mb: int | None,
) -> dict[str, Any]:
    """allocations: die primäre zuerst. Der Startbefehl bleibt unersetzt in STARTUP,
    die Yolks-Images setzen die Platzhalter im Container selbst ein."""
    env = {k: v for k, v in variables.items() if k not in RESERVED}
    if server.startup:
        env["STARTUP"] = server.startup
    memory = server.memory_mb or host_memory_mb
    if memory:
        env["SERVER_MEMORY"] = str(memory)
    if allocations:
        env["SERVER_IP"] = allocations[0].ip
        env["SERVER_PORT"] = str(allocations[0].port)
    ports = [
        {"host": a.port, "container": a.port, "proto": proto}
        for a in allocations
        for proto in ("tcp", "udp")
    ]
    return {
        "name": container_name(server.id),
        "image": server.image,
        "ports": ports,
        "env": env,
        "memory_mb": server.memory_mb,
        "cpus": server.cpus,
        "data": True,
    }
