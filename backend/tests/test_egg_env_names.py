import pytest

from app.schemas.egg import clean_env_name
from app.services import eggio


@pytest.mark.parametrize("name", ["SERVER_PORT", "SteamAppId", "MaxPlayers", "_x", "a1_B2"])
def test_env_names_keep_their_case(name):
    assert clean_env_name(name) == name


@pytest.mark.parametrize("name", ["", "1ABC", "A-B", "A B", "A;B", "Ä", "A" * 65])
def test_invalid_env_names_are_rejected(name):
    with pytest.raises(ValueError):
        clean_env_name(name)


def _var(env):
    return {
        "name": env,
        "description": "",
        "env_variable": env,
        "default_value": "1",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|string",
    }


def _egg(startup, variables):
    return {
        "meta": {"version": "PTDL_v2"},
        "name": "Test egg",
        "description": "",
        "docker_images": {"Java": "ghcr.io/ptero-eggs/yolks:java_21"},
        "startup": startup,
        "config": {},
        "scripts": {
            "installation": {"script": "", "container": "alpine:3.4", "entrypoint": "ash"}
        },
        "variables": variables,
    }


def test_import_keeps_mixed_case_variables():
    raw = [_var("SteamAppId"), _var("MAX_PLAYERS")]
    fields, _config, warnings = eggio.import_egg(_egg("./run {{SteamAppId}}", raw))
    assert [v["env_variable"] for v in fields["variables"]] == ["SteamAppId", "MAX_PLAYERS"]
    assert not any("skipped" in w for w in warnings)


def test_import_keeps_startup_spacing_and_removes_line_breaks():
    fields, _config, _warnings = eggio.import_egg(_egg('echo  "a  b";\r\n./run', []))
    startup = fields["startup"]
    assert "\n" not in startup and "\r" not in startup
    assert startup.startswith('echo  "a  b";')
    assert startup.endswith("./run")


def test_import_rejects_overlong_startup():
    with pytest.raises(ValueError):
        eggio.import_egg(_egg("x" * 2049, []))
