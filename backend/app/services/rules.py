"""Validation rules for variables in Pterodactyl style, for example required|integer."""

import re

_TOKEN = re.compile(r"regex:/(?P<rx>.*?)/(?P<fl>[a-z]*)(?=\||$)|(?P<plain>[^|]+)", re.DOTALL)
_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)")
_INTEGER = re.compile(r"-?\d+")
_ALPHA_NUM = re.compile(r"[A-Za-z0-9]+")
_ALPHA_DASH = re.compile(r"[A-Za-z0-9_-]+")
_BOOLEANS = {"0", "1", "true", "false"}

SIMPLE = {
    "required",
    "nullable",
    "string",
    "integer",
    "numeric",
    "boolean",
    "alpha_num",
    "alpha_dash",
}
LISTS = {"in", "not_in"}
MAX_RULES_CHARS = 512
MAX_REGEX_CHARS = 200

Parsed = list[tuple[str, list[str], str]]


def parse(rules: str) -> Parsed:
    """Splits the rules into (name, arguments, original text)."""
    parsed: Parsed = []
    for match in _TOKEN.finditer(rules):
        if match.group("rx") is not None:
            parsed.append(("regex", [match.group("rx"), match.group("fl")], match.group(0)))
            continue
        token = match.group("plain").strip()
        if not token:
            continue
        name, _, arg = token.partition(":")
        args = [a.strip() for a in arg.split(",")] if arg else []
        parsed.append((name.strip(), args, token))
    return parsed


def _flags(letters: str) -> int:
    return re.IGNORECASE if "i" in letters else 0


def _problem(name: str, args: list[str]) -> str | None:
    if name in SIMPLE:
        return f"The rule {name} takes no value." if args else None
    if name in ("min", "max"):
        if len(args) == 1 and _NUMBER.fullmatch(args[0]):
            return None
        return f"The rule {name} needs one number."
    if name == "between":
        if len(args) == 2 and all(_NUMBER.fullmatch(a) for a in args):
            if float(args[0]) <= float(args[1]):
                return None
        return "The rule between needs two numbers, the smaller one first."
    if name in LISTS:
        return None if args else f"The rule {name} needs a list of values."
    if name == "regex":
        if len(args) != 2:
            return "The rule regex must look like regex:/pattern/."
        if len(args[0]) > MAX_REGEX_CHARS:
            return f"A regex may have at most {MAX_REGEX_CHARS} characters."
        try:
            re.compile(args[0], _flags(args[1]))
        except re.error:
            return "The regex of the rule is invalid."
        return None
    return f"Unknown rule: {name}."


def problems(rules: str) -> list[str]:
    """Checks on save if all rules are known and well formed."""
    if len(rules) > MAX_RULES_CHARS:
        return [f"The rules may have at most {MAX_RULES_CHARS} characters."]
    found = []
    for name, args, _raw in parse(rules):
        problem = _problem(name, args)
        if problem:
            found.append(problem)
    return found


def drop_unknown(rules: str) -> tuple[str, list[str]]:
    """For the import: keeps only usable rules and lists the removed ones."""
    kept: list[str] = []
    dropped: list[str] = []
    for name, args, raw in parse(rules[: MAX_RULES_CHARS * 4]):
        if _problem(name, args):
            dropped.append(name)
        else:
            kept.append(raw)
    text = "|".join(kept)
    if len(text) > MAX_RULES_CHARS:
        return "", [*dropped, "all (too long)"]
    return text, dropped


def validate(value: str, rules: str) -> str | None:
    """Returns an error message or None if the value fits."""
    parsed = [p for p in parse(rules) if _problem(p[0], p[1]) is None]
    names = {name for name, _args, _raw in parsed}
    if value == "":
        return "A value is required." if "required" in names else None

    for name, _args, _raw in parsed:
        if name == "integer" and not _INTEGER.fullmatch(value):
            return "Must be a whole number."
        if name == "numeric" and not _NUMBER.fullmatch(value):
            return "Must be a number."
        if name == "boolean" and value not in _BOOLEANS:
            return "Must be true or false."
        if name == "alpha_num" and not _ALPHA_NUM.fullmatch(value):
            return "May only contain letters and digits."
        if name == "alpha_dash" and not _ALPHA_DASH.fullmatch(value):
            return "May only contain letters, digits, hyphens and underscores."

    # For number rules the value counts, otherwise the length.
    numeric = "integer" in names or "numeric" in names
    size = float(value) if numeric else float(len(value))
    unit = "" if numeric else " characters"
    for name, args, _raw in parsed:
        if name == "min" and size < float(args[0]):
            return f"Must be at least {args[0]}{unit}."
        if name == "max" and size > float(args[0]):
            return f"Must be at most {args[0]}{unit}."
        if name == "between" and not float(args[0]) <= size <= float(args[1]):
            return f"Must be between {args[0]} and {args[1]}{unit}."
        if name == "in" and value not in args:
            return "Must be one of: " + ", ".join(args) + "."
        if name == "not_in" and value in args:
            return "This value is not allowed."
        if name == "regex" and not re.search(args[0], value, _flags(args[1])):
            return "The format is invalid."
    return None
