import asyncio
import hashlib
import importlib
import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.agentlink.protocol import CommandResult
from app.models import Allocation, Server
from app.models.server import ServerBackup
from app.services import node_transfer
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login

ARCHIVE = os.urandom(45)  # five parts of 10 bytes
SHA = hashlib.sha256(ARCHIVE).hexdigest()


class FakeAgents:
    """Plays both nodes, including the HTTP calls they make to the relay."""

    def __init__(self):
        self.calls = []
        self.errors = {}
        self.fetched = b""

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((str(node_id), action, params))
        error = self.errors.get(action)
        if error:
            return CommandResult(type="result", id="x", ok=False, error=error, data={})
        data = {}
        if action == "backup.status":
            data = {"state": "ok"}
            if params["kind"] == "create":
                data.update(size=len(ARCHIVE), sha256=SHA)
        elif action == "backup.upload":
            size = params["part_size"]
            for index, url in enumerate(params["urls"]):
                job = node_transfer.job_by_token(url.split("/")[-3])
                chunk = ARCHIVE[index * size : (index + 1) * size]

                async def body(chunk=chunk):
                    yield chunk

                await node_transfer.store_part(job, index, len(chunk), body())
        elif action == "backup.fetch":
            job = node_transfer.job_by_token(params["url"].split("/")[-2])
            self.fetched = b"".join(node_transfer.read_archive(job))
            if hashlib.sha256(self.fetched).hexdigest() != params["sha256"]:
                return CommandResult(type="result", id="x", ok=False, error="sha", data={})
        return CommandResult(type="result", id="x", ok=True, error=None, data=data)

    def actions(self, node_id=None):
        return [a for n, a, _ in self.calls if node_id is None or n == str(node_id)]


@pytest.fixture
def setup(client, user, db_session, monkeypatch, tmp_path):
    agents = FakeAgents()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", agents)
    monkeypatch.setattr(node_transfer, "POLL_SECONDS", 0)
    monkeypatch.setattr(node_transfer, "PART_SIZE", 10)
    monkeypatch.setenv("EPICWING_TRANSFER_DIR", str(tmp_path / "relay"))
    settings = SimpleNamespace(epicwing_public_url="https://panel.test/")
    monkeypatch.setattr(node_transfer, "get_settings", lambda: settings)
    monkeypatch.setattr(
        importlib.import_module("app.api.node_transfer"), "get_settings", lambda: settings
    )
    engine = db_session.get_bind()
    monkeypatch.setattr(
        node_transfer, "open_session", lambda: Session(engine, expire_on_commit=False)
    )
    # Run the transfer right away in the test instead of in the background.
    started = []
    monkeypatch.setattr(node_transfer, "start", lambda job: _register(job, started))

    headers = _login(client, user)
    source = _create(client, headers, "source")
    target = _create(client, headers, "target")
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run {{SERVER_PORT}}")
    old_port = make_allocations(client, headers, source, 25001, 25001)[0]
    new_port = make_allocations(client, headers, target, 25565, 25566, ip="198.51.100.7")[0]
    created = client.post(
        "/api/servers",
        json={
            "name": "Game",
            "node_id": source,
            "egg_id": egg_id,
            "allocation_id": old_port,
            "owner_id": str(user.id),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    server_id = created.json()["id"]
    server = db_session.get(Server, uuid.UUID(server_id))
    server.status = "offline"
    db_session.commit()
    return SimpleNamespace(
        headers=headers,
        agents=agents,
        source=source,
        target=target,
        old_port=old_port,
        new_port=new_port,
        server=server,
        url=f"/api/servers/{server_id}/node-transfer",
        started=started,
        relay=tmp_path / "relay",
    )


def _register(job, started):
    node_transfer._jobs[job.server_id] = job
    node_transfer._by_token[node_transfer._token_key(job.token)] = job
    started.append(job)


def _start(client, s, **extra):
    body = {"node_id": s.target, "allocation_id": s.new_port, **extra}
    return client.post(s.url, json=body, headers=s.headers)


def _run(s):
    asyncio.run(node_transfer.run(s.started[-1]))


def test_moves_the_server_to_the_new_node(client, db_session, setup):
    s = setup
    response = _start(client, s)
    assert response.status_code == 202, response.text
    db_session.refresh(s.server)
    assert s.server.status == "transferring"

    _run(s)

    assert s.started[-1].step == "done", s.started[-1].error
    assert s.agents.fetched == ARCHIVE
    db_session.expire_all()
    assert str(s.server.node_id) == s.target
    assert s.server.status == "offline"
    assert db_session.get(Allocation, uuid.UUID(s.new_port)).server_id == s.server.id
    assert db_session.get(Allocation, uuid.UUID(s.old_port)).server_id is None
    assert s.agents.actions(s.source)[:2] == ["backup.create", "backup.status"]
    assert "container.remove" in s.agents.actions(s.source)
    target_actions = s.agents.actions(s.target)
    assert target_actions.index("container.create") < target_actions.index("backup.fetch")
    assert target_actions.index("backup.fetch") < target_actions.index("backup.restore")
    assert not s.started[-1].folder.exists()
    assert client.get(s.url, headers=s.headers).json()["step"] == "done"


def test_failure_keeps_the_server_on_the_old_node(client, db_session, setup):
    s = setup
    s.agents.errors["backup.restore"] = "disk full"
    assert _start(client, s).status_code == 202
    _run(s)

    job = s.started[-1]
    assert job.step == "failed"
    assert job.error == "disk full"
    db_session.expire_all()
    assert str(s.server.node_id) == s.source
    assert s.server.status == "offline"
    assert "disk full" in s.server.last_error
    assert db_session.get(Allocation, uuid.UUID(s.old_port)).server_id == s.server.id
    # The half restored copy on the new node is removed again (once before create).
    assert s.agents.actions(s.target).count("container.remove") == 2
    assert "container.remove" not in s.agents.actions(s.source)


def test_running_server_is_refused(client, db_session, setup):
    s = setup
    s.server.status = "running"
    db_session.commit()
    assert _start(client, s).status_code == 409
    assert not s.started


def test_port_must_be_free_and_on_the_target(client, db_session, setup):
    s = setup
    assert _start(client, s, allocation_id=s.old_port).status_code == 409
    response = client.post(
        s.url, json={"node_id": s.source, "allocation_id": s.new_port}, headers=s.headers
    )
    assert response.status_code == 409


def test_local_backups_need_confirmation(client, db_session, setup):
    s = setup
    kept = ServerBackup(server_id=s.server.id, name="s3", status="ok", remote_state="ok")
    lost = ServerBackup(server_id=s.server.id, name="local", status="ok")
    db_session.add_all([kept, lost])
    db_session.commit()
    assert client.get(s.url, headers=s.headers).json()["local_only_backups"] == 1
    assert _start(client, s).status_code == 409

    kept_id, lost_id = kept.id, lost.id
    assert _start(client, s, delete_local_backups=True).status_code == 202
    _run(s)
    db_session.expunge_all()
    assert db_session.get(ServerBackup, lost_id) is None
    assert db_session.get(ServerBackup, kept_id).local is False


def test_targets_list_free_ports_of_other_nodes(client, setup):
    s = setup
    nodes = client.get(s.url + "/targets", headers=s.headers).json()
    assert [n["id"] for n in nodes] == [s.target]
    assert [a["port"] for a in nodes[0]["allocations"]] == [25565, 25566]


def test_relay_needs_a_valid_token(client, setup):
    assert client.get("/api/node-transfers/nope/archive").status_code == 404
    assert client.put("/api/node-transfers/nope/parts/0", content=b"x").status_code == 404


def test_relay_over_http(client, setup):
    s = setup
    assert _start(client, s).status_code == 202
    job = s.started[-1]
    job.step = "upload"
    job.size = 15
    job.parts = 2
    first = client.put(f"/api/node-transfers/{job.token}/parts/0", content=b"0123456789")
    assert first.status_code == 200
    assert first.headers["etag"]
    too_big = client.put(f"/api/node-transfers/{job.token}/parts/1", content=b"x" * 11)
    assert too_big.status_code == 409
    assert (
        client.put(f"/api/node-transfers/{job.token}/parts/1", content=b"abcde").status_code == 200
    )
    # Not ready while the upload step runs.
    assert client.get(f"/api/node-transfers/{job.token}/archive").status_code == 409
    job.step = "download"
    archive = client.get(f"/api/node-transfers/{job.token}/archive")
    assert archive.status_code == 200
    assert archive.content == b"0123456789abcde"


def test_files_are_blocked_during_a_transfer(client, db_session, setup):
    s = setup
    s.server.status = "transferring"
    db_session.commit()
    server_url = s.url.removesuffix("/node-transfer")
    assert client.get(server_url + "/files?path=/", headers=s.headers).status_code == 409


def test_restart_resets_an_interrupted_transfer(db_session, setup):
    s = setup
    s.server.status = "transferring"
    db_session.commit()
    node_transfer.reset_interrupted()
    db_session.expire_all()
    assert s.server.status == "offline"
    assert "restarted" in s.server.last_error


@pytest.fixture(autouse=True)
def _clear_jobs():
    yield
    node_transfer._jobs.clear()
    node_transfer._by_token.clear()
