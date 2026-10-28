import re
from pathlib import Path

from app.agentlink import protocol

APP = Path(__file__).resolve().parents[1] / "app"
SEND = re.compile(r'(?:broker\.send|_send)\(\s*[\w.]+,\s*"([a-z]+\.[a-z_]+)"')


def test_every_action_used_by_the_backend_is_known():
    used: set[str] = set()
    for path in APP.rglob("*.py"):
        if path.name == "protocol.py":
            continue
        used.update(SEND.findall(path.read_text(encoding="utf-8")))
    assert "backup.read" in used
    unknown = used - set(protocol.COMMAND_ACTIONS)
    assert not unknown, f"not in COMMAND_ACTIONS: {sorted(unknown)}"
