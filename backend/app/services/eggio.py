"""Import und Export von Eggs im Pterodactyl-Format (PTDL_v1 und PTDL_v2)."""

import json
import re
from datetime import UTC, datetime
from typing import Any

from app.services import rules as rule_engine

SUPPORTED = {"PTDL_v1", "PTDL_v2"}
CONFIG_KEYS = ("files", "startup", "logs")
# Features, die das Panel selbst umsetzt. eula: die Oberfläche erkennt die Meldung in der Konsole.
SUPPORTED_FEATURES = frozenset({"eula"})
MAX_CONFIG_CHARS = 65_535
AUTHOR = "noreply@epicwing.invalid"
DEFAULT_INSTALLER = "ghcr.io/pterodactyl/installers:alpine"

_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_BAD_NAME = re.compile(r"[^A-Za-z0-9 ._-]+")
_SPACES = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


MAX_STARTUP_CHARS = 2048


def _startup(value: Any) -> str:
    """Startbefehl: Steuerzeichen werden zu Leerzeichen, sonst bleibt er unverändert.

    Mehrfache Leerzeichen bleiben stehen, weil sie in Anführungszeichen vorkommen können.
    Ist der Befehl länger als das Schema erlaubt, lehnt der Import ab, statt still zu kürzen.
    """
    text = _CONTROL.sub(" ", "" if value is None else str(value)).strip()
    if len(text) > MAX_STARTUP_CHARS:
        raise ValueError(f"The startup command is longer than {MAX_STARTUP_CHARS} characters.")
    return text


def _line(value: Any, limit: int) -> str:
    """Einzeiliger Text: Steuerzeichen werden zu Leerzeichen, Länge begrenzt."""
    text = "" if value is None else str(value)
    return _SPACES.sub(" ", _CONTROL.sub(" ", text)).strip()[:limit]


def _name(value: Any, fallback: str, label: str, warnings: list[str]) -> str:
    original = "" if value is None else str(value)
    name = _SPACES.sub(" ", _BAD_NAME.sub(" ", original)).strip().lstrip(" ._-")[:64].strip()
    if not name:
        warnings.append(f"{label} is missing or invalid, using {fallback}.")
        return fallback
    if name != original:
        warnings.append(f"{label} was changed to {name}.")
    return name


def _flag(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _images(data: dict[str, Any]) -> list[str]:
    found = data.get("docker_images")
    if isinstance(found, dict):
        return [str(v).strip() for v in found.values() if isinstance(v, str) and v.strip()]
    older = data.get("images")
    if isinstance(older, list):
        return [str(v).strip() for v in older if isinstance(v, str) and v.strip()]
    single = data.get("image")
    return [single.strip()] if isinstance(single, str) and single.strip() else []


def _variable(raw: dict[str, Any], env: str, warnings: list[str]) -> dict[str, Any]:
    rules, dropped = rule_engine.drop_unknown(str(raw.get("rules") or ""))
    if dropped:
        warnings.append(f"Variable {env}: unsupported rules removed ({', '.join(dropped)}).")
    rules = rules or "nullable|string"
    default = _line(raw.get("default_value"), 1024)
    if default and rule_engine.validate(default, rules):
        warnings.append(f"Variable {env}: the default does not match its rules, cleared.")
        default = ""
    return {
        "name": _name(raw.get("name"), env, f"The name of {env}", warnings),
        "env_variable": env,
        "default_value": default,
        "description": _line(raw.get("description"), 255),
        "user_editable": _flag(raw.get("user_editable"), True),
        "user_viewable": _flag(raw.get("user_viewable"), True),
        "rules": rules,
    }


def import_egg(data: dict[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
    """Gibt (Felder für EggCreate ohne nest_id, config als JSON-Text, Hinweise) zurück.

    Wirft ValueError, wenn die Datei kein brauchbares Egg ist.
    """
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("version") not in SUPPORTED:
        raise ValueError("This is not a Pterodactyl egg file (PTDL_v1 or PTDL_v2).")
    warnings: list[str] = []

    images = _images(data)
    if not images:
        raise ValueError("The egg does not contain a Docker image.")
    if len(images) > 1:
        warnings.append(f"Only the first Docker image is used: {images[0]}.")
    raw_features = data.get("features")
    features = (
        [f for f in raw_features if isinstance(f, str)] if isinstance(raw_features, list) else []
    )
    ignored = [f for f in features if f not in SUPPORTED_FEATURES]
    if ignored:
        warnings.append(f"Egg features are not supported and were ignored: {', '.join(ignored)}.")

    variables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in data.get("variables") or []:
        env = str(raw.get("env_variable") or "").strip() if isinstance(raw, dict) else ""
        if not _ENV.fullmatch(env) or env in seen:
            warnings.append(f"A variable was skipped (invalid or doubled name): {env or '?'}.")
            continue
        seen.add(env)
        variables.append(_variable(raw, env, warnings))

    source = data.get("config") if isinstance(data.get("config"), dict) else {}
    config: dict[str, Any] = {k: source[k] for k in CONFIG_KEYS if k in source}
    if features:
        config["features"] = features
    install = (data.get("scripts") or {}).get("installation") or {}
    if not isinstance(install, dict):
        install = {}
    extra = {k: install[k] for k in ("container", "entrypoint") if isinstance(install.get(k), str)}
    if extra:
        config["install"] = extra
    config_text = json.dumps(config, ensure_ascii=False)
    if len(config_text) > MAX_CONFIG_CHARS:
        raise ValueError("The config section of the egg is too large.")

    stop = source.get("stop")
    stop_command = _line(stop, 255) if isinstance(stop, str) and not stop.startswith("^") else ""
    script = install.get("script")
    if isinstance(script, str):
        script = script.replace("\r\n", "\n").replace("\r", "\n")
    fields = {
        "name": _name(data.get("name"), "Imported egg", "The egg name", warnings),
        "description": _line(data.get("description"), 255),
        "docker_image": images[0],
        "startup": _startup(data.get("startup")),
        "stop_command": stop_command,
        "install_script": script if isinstance(script, str) else "",
        "variables": variables,
    }
    return fields, config_text, warnings


def _text(value: Any) -> str:
    if value is None:
        return "{}"
    return value if isinstance(value, str) else json.dumps(value)


def export_egg(egg: Any, variables: list[Any]) -> dict[str, Any]:
    """Baut das PTDL_v2-JSON aus einem Egg und seinen Variablen."""
    try:
        stored = json.loads(egg.config or "{}")
    except ValueError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    install = stored.get("install") if isinstance(stored.get("install"), dict) else {}
    config = {key: _text(stored.get(key)) for key in CONFIG_KEYS}
    config["stop"] = egg.stop_command or "^C"
    stored_features = stored.get("features")
    features = (
        [f for f in stored_features if isinstance(f, str)]
        if isinstance(stored_features, list)
        else []
    )
    return {
        "_comment": "Exported by EpicWing in the Pterodactyl egg format.",
        "meta": {"version": "PTDL_v2"},
        "exported_at": datetime.now(UTC).isoformat(),
        "name": egg.name,
        "author": AUTHOR,
        "description": egg.description,
        "features": features or None,
        "docker_images": {egg.docker_image: egg.docker_image},
        "file_denylist": [],
        "startup": egg.startup,
        "config": config,
        "scripts": {
            "installation": {
                "script": egg.install_script,
                "container": install.get("container") or DEFAULT_INSTALLER,
                "entrypoint": install.get("entrypoint") or "ash",
            }
        },
        "variables": [
            {
                "name": v.name,
                "description": v.description,
                "env_variable": v.env_variable,
                "default_value": v.default_value,
                "user_viewable": v.user_viewable,
                "user_editable": v.user_editable,
                "rules": v.rules,
                "field_type": "text",
            }
            for v in variables
        ],
    }
