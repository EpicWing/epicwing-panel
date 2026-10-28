import json
from types import SimpleNamespace

import pytest

from app.services import eggio

PTDL = {
    "_comment": "test",
    "meta": {"version": "PTDL_v2"},
    "name": "Test Game",
    "author": "someone@example.test",
    "description": "A game\nwith two lines",
    "features": ["eula"],
    "docker_images": {
        "Java 17": "ghcr.io/pterodactyl/yolks:java_17",
        "Java 21": "ghcr.io/pterodactyl/yolks:java_21",
    },
    "file_denylist": [],
    "startup": "java -Xmx{{SERVER_MEMORY}}M -jar {{SERVER_JARFILE}}",
    "config": {
        "files": "{}",
        "startup": '{"done": ")! For help"}',
        "logs": "{}",
        "stop": "stop",
    },
    "scripts": {
        "installation": {
            "script": "#!/bin/bash\r\necho hi",
            "container": "alpine:3.4",
            "entrypoint": "bash",
        }
    },
    "variables": [
        {
            "name": "Server Jar File",
            "description": "The jar",
            "env_variable": "SERVER_JARFILE",
            "default_value": "server.jar",
            "user_viewable": True,
            "user_editable": True,
            "rules": r"required|regex:/^([\w\d._-]+)(\.jar)$/",
            "field_type": "text",
        },
        {
            "name": "Max players",
            "description": "",
            "env_variable": "MAX_PLAYERS",
            "default_value": "20",
            "user_viewable": 1,
            "user_editable": 0,
            "rules": "required|integer|url",
            "field_type": "text",
        },
    ],
}


def test_import_maps_the_fields():
    data, config, warnings = eggio.import_egg(PTDL)
    assert data["name"] == "Test Game"
    assert data["description"] == "A game with two lines"
    assert data["docker_image"] == "ghcr.io/pterodactyl/yolks:java_17"
    assert data["stop_command"] == "stop"
    assert data["install_script"] == "#!/bin/bash\necho hi"
    jar, players = data["variables"]
    assert jar["rules"] == r"required|regex:/^([\w\d._-]+)(\.jar)$/"
    assert players["rules"] == "required|integer"
    assert (players["user_viewable"], players["user_editable"]) == (True, False)
    saved = json.loads(config)
    assert saved["startup"] == PTDL["config"]["startup"]
    assert saved["install"] == {"container": "alpine:3.4", "entrypoint": "bash"}
    assert "stop" not in saved
    assert any("MAX_PLAYERS" in w and "url" in w for w in warnings)
    assert any("first Docker image" in w for w in warnings)
    assert not any("eula" in w for w in warnings)
    assert "eula" in saved["features"]


def test_import_cleans_names_and_defaults():
    egg = {
        "meta": {"version": "PTDL_v1"},
        "name": "Rust (Staging)",
        "image": "ghcr.io/x/rust:latest",
        "config": {"stop": "^C"},
        "variables": [
            {"name": "Slots", "env_variable": "SLOTS", "default_value": "abc", "rules": "integer"},
            {"name": "Again", "env_variable": "SLOTS"},
            {"name": "Bad", "env_variable": "bad-name"},
        ],
    }
    data, _config, warnings = eggio.import_egg(egg)
    assert data["name"] == "Rust Staging"
    assert data["stop_command"] == ""
    assert [v["env_variable"] for v in data["variables"]] == ["SLOTS"]
    assert data["variables"][0]["default_value"] == ""
    assert len(warnings) == 4


@pytest.mark.parametrize(
    "egg",
    [
        {},
        {"meta": {"version": "other"}},
        {"meta": {"version": "PTDL_v2"}, "name": "x"},
    ],
)
def test_import_rejects_other_files(egg):
    with pytest.raises(ValueError):
        eggio.import_egg(egg)


def test_export_builds_ptdl_v2():
    _data, config, _warnings = eggio.import_egg(PTDL)
    egg = SimpleNamespace(
        name="Game",
        description="d",
        docker_image="img:1",
        startup="run",
        stop_command="",
        install_script="echo",
        config=config,
    )
    variable = SimpleNamespace(
        name="A",
        env_variable="A",
        default_value="1",
        description="",
        user_viewable=True,
        user_editable=False,
        rules="required|integer",
    )
    out = eggio.export_egg(egg, [variable])
    assert out["meta"] == {"version": "PTDL_v2"}
    assert out["config"]["stop"] == "^C"
    assert out["config"]["startup"] == PTDL["config"]["startup"]
    assert out["docker_images"] == {"img:1": "img:1"}
    assert out["scripts"]["installation"]["container"] == "alpine:3.4"
    assert out["variables"][0]["rules"] == "required|integer"
    assert json.dumps(out)
