import json
from pathlib import Path

from app.services import eggio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eggs"


def test_unturned_ships_its_install_script():
    data = json.loads((FIXTURES / "games-unturned.json").read_text())
    script = data["scripts"]["installation"]["script"]
    assert "steamcmd" in script and "app_update" in script
    fields, _config, _warnings = eggio.import_egg(data)
    assert fields["install_script"].strip() == script.strip()


def test_bundled_install_scripts_use_unix_line_endings():
    for path in FIXTURES.glob("*.json"):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text())
        script = ((data.get("scripts") or {}).get("installation") or {}).get("script") or ""
        assert "\r" not in script, path.name


def test_import_converts_windows_line_endings():
    data = {
        "meta": {"version": "PTDL_v2"},
        "name": "CRLF test",
        "startup": "./run",
        "docker_images": {"steamcmd": "ghcr.io/ptero-eggs/steamcmd:debian"},
        "scripts": {"installation": {"script": "#!/bin/bash\r\necho hi\r\n"}},
    }
    fields, _config, _warnings = eggio.import_egg(data)
    assert fields["install_script"] == "#!/bin/bash\necho hi\n"
