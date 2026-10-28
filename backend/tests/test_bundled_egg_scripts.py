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
