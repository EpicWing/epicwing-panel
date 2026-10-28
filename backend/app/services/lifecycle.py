"""Container-Spezifikation eines Servers, so wie der Node-Agent sie erwartet."""

import json
import uuid
from typing import Any

from app.services.eggio import DEFAULT_INSTALLER

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


def build_install_spec(
    server: Any,
    allocations: list[Any],
    variables: dict[str, str],
    host_memory_mb: int | None,
    install_script: str,
    installer_image: str = DEFAULT_INSTALLER,
    installer_entrypoint: str = "ash",
) -> dict[str, Any]:
    """Build the one-shot install job for the server's data directory."""
    spec = build_spec(server, allocations, variables, host_memory_mb)
    spec.pop("ports", None)
    spec.pop("data", None)
    spec["install_script"] = install_script
    spec["installer_image"] = installer_image
    spec["installer_entrypoint"] = installer_entrypoint
    return spec


def install_settings(egg: Any) -> tuple[str, str]:
    """Read the optional Pterodactyl installer image and entrypoint."""
    try:
        config = json.loads(egg.config or "{}")
    except (TypeError, ValueError):
        config = {}
    install = config.get("install") if isinstance(config, dict) else None
    if not isinstance(install, dict):
        install = {}
    image = install.get("container")
    entrypoint = install.get("entrypoint")
    resolved_image = image if isinstance(image, str) and image else DEFAULT_INSTALLER
    if isinstance(entrypoint, str) and entrypoint:
        resolved_entrypoint = entrypoint
    else:
        # Pterodactyl eggs normally specify this explicitly. Imported eggs
        # without an install.entrypoint still need the shell matching the
        # installer image instead of always trying Alpine's `ash`.
        lowered = resolved_image.lower()
        resolved_entrypoint = "bash" if any(word in lowered for word in ("debian", "ubuntu", "alpine-glibc")) else "ash"
    return resolved_image, resolved_entrypoint
