"""Moves a stopped server to another node.

The agents already know how to upload a backup in parts and how to download one from a
URL (that is how the object storage works). For a node transfer the panel plays that
storage: the old node packs the server into a temporary backup and uploads it to the
panel, the new node downloads it from there, checks the SHA-256 sum and restores it.

The database points to the new node only at the very end. Until then an aborted transfer
leaves the server where it was, and the files on the old node are never touched.
"""

import asyncio
import contextlib
import hashlib
import logging
import os
import secrets
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agentlink.commands import AgentOffline
from app.config import get_settings
from app.db import get_engine
from app.models import Allocation, Node, Server
from app.models.server import ServerBackup
from app.services import audit, lifecycle

log = logging.getLogger(__name__)

# The nginx in front of the panel accepts 16 MiB per request.
PART_SIZE = 15 * 1024 * 1024
MAX_PARTS = 10_000  # the most the agent takes
POLL_SECONDS = 3.0
# Longest wait for one step, in seconds.
STEP_TIMEOUT = {"backup": 6 * 3600, "upload": 12 * 3600, "download": 12 * 3600, "restore": 6 * 3600}
READ_BLOCK = 1024 * 1024
TRANSFER_STATUS = "transferring"


def open_session() -> Session:
    """A session of its own: the transfer outlives the request. Replaced in the tests."""
    return Session(get_engine(), expire_on_commit=False)


def storage_dir() -> Path:
    """Where the archive waits between the two nodes. /tmp is often in memory."""
    default = "/var/tmp/epicwing-transfers"  # noqa: S108 - a fixed folder, created with 0700
    return Path(os.environ.get("EPICWING_TRANSFER_DIR", default))


@dataclass
class Job:
    server_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    allocation_id: uuid.UUID
    actor_id: uuid.UUID | None
    delete_local_backups: bool
    backup_id: uuid.UUID = field(default_factory=uuid.uuid4)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    step: str = "backup"
    error: str | None = None
    size: int = 0
    sha256: str = ""
    parts: int = 0
    received: set[int] = field(default_factory=set)
    sent: int = 0
    started: float = field(default_factory=time.time)

    @property
    def folder(self) -> Path:
        return storage_dir() / str(self.backup_id)

    @property
    def name(self) -> str:
        return lifecycle.container_name(self.server_id)

    def progress(self) -> int | None:
        if self.step == "upload" and self.parts:
            return int(100 * len(self.received) / self.parts)
        if self.step == "download" and self.size:
            return min(100, int(100 * self.sent / self.size))
        return None

    def public(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "error": self.error,
            "progress": self.progress(),
            "size": self.size or None,
            "target_node_id": str(self.target_node_id),
            "running": self.step not in ("done", "failed"),
        }


class TransferError(Exception):
    """A step failed. The message is shown to the admin."""


_jobs: dict[uuid.UUID, Job] = {}
_by_token: dict[str, Job] = {}
_tasks: set[asyncio.Task[None]] = set()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def job_for(server_id: uuid.UUID) -> Job | None:
    return _jobs.get(server_id)


def job_by_token(token: str) -> Job | None:
    return _by_token.get(_token_key(token))


def is_running(server_id: uuid.UUID) -> bool:
    job = _jobs.get(server_id)
    return job is not None and job.step not in ("done", "failed")


# ---------------------------------------------------------------- relay storage


def part_path(job: Job, index: int) -> Path:
    return job.folder / f"part-{index:05d}"


async def store_part(job: Job, index: int, length: int, chunks: AsyncIterator[bytes]) -> str:
    """Writes one part. Returns the ETag the agent expects."""
    if job.step != "upload":
        raise TransferError("No upload is expected for this transfer.")
    if not 0 <= index < job.parts:
        raise TransferError("Unknown part.")
    if length < 0 or length > PART_SIZE:
        raise TransferError("The part has an invalid size.")
    job.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = part_path(job, index)
    temp = target.with_suffix(".tmp")
    written = 0
    digest = hashlib.md5(usedforsecurity=False)
    with temp.open("wb") as out:
        async for chunk in chunks:
            written += len(chunk)
            if written > length:
                break
            out.write(chunk)
            digest.update(chunk)
    if written != length:
        temp.unlink(missing_ok=True)
        raise TransferError("The part is incomplete.")
    temp.replace(target)
    job.received.add(index)
    return f'"{digest.hexdigest()}"'


def archive_ready(job: Job) -> bool:
    return job.step == "download" and len(job.received) == job.parts


def read_archive(job: Job) -> Iterator[bytes]:
    """Yields the parts one after the other. Counts what was sent for the progress."""
    job.sent = 0
    for index in range(job.parts):
        with part_path(job, index).open("rb") as part:
            while block := part.read(READ_BLOCK):
                job.sent += len(block)
                yield block


def _drop_files(job: Job) -> None:
    shutil.rmtree(job.folder, ignore_errors=True)


# ---------------------------------------------------------------- agent calls


def _broker():
    # Looked up at call time so the tests can replace it.
    from app.api import servers as servers_api

    return servers_api.broker


async def _call(node_id: uuid.UUID, action: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await _broker().send(node_id, action, params)
    except AgentOffline:
        raise TransferError("A node is offline.") from None
    except TimeoutError:
        raise TransferError("A node did not answer in time.") from None
    if not result.ok:
        raise TransferError(result.error or f"{action} failed on the node.")
    return result.data or {}


async def _wait(job: Job, node_id: uuid.UUID, kind: str, timeout: int) -> dict[str, Any]:
    """Asks the node until the job of this kind is finished."""
    deadline = time.monotonic() + timeout
    params = {"name": job.name, "id": str(job.backup_id), "kind": kind}
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            data = await _call(node_id, "backup.status", params)
        except TransferError:
            if time.monotonic() > deadline:
                raise
            continue
        state = data.get("state")
        if state == "ok":
            return data
        if state != "running":
            raise TransferError(str(data.get("error") or f"The {kind} step failed on the node."))
        if time.monotonic() > deadline:
            raise TransferError(f"The {kind} step took too long.")


async def _quietly(node_id: uuid.UUID, action: str, params: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):
        await _broker().send(node_id, action, params)


# ---------------------------------------------------------------- the transfer


def _relay_base() -> str:
    base = get_settings().epicwing_public_url.strip().rstrip("/")
    if not base:
        raise TransferError("EPICWING_PUBLIC_URL is not set, the nodes cannot reach the panel.")
    return base


def _target_spec(db: Session, job: Job) -> dict[str, Any]:
    from app.api import servers as servers_api

    server = db.get(Server, job.server_id)
    allocation = db.get(Allocation, job.allocation_id)
    node = db.get(Node, job.target_node_id)
    if server is None or allocation is None or node is None:
        raise TransferError("The server, the port or the node no longer exists.")
    if allocation.server_id not in (None, server.id) or allocation.node_id != node.id:
        raise TransferError("The port on the new node is no longer free.")
    out = servers_api._outs(db, [server], reveal_secrets=True)[0]
    return lifecycle.build_spec(server, [allocation], out.variables, node.ram_total_mb)


def _switch(db: Session, job: Job) -> None:
    """The last step: the database points to the new node."""
    server = db.get(Server, job.server_id)
    allocation = db.get(Allocation, job.allocation_id)
    if server is None or allocation is None:
        raise TransferError("The server or the port no longer exists.")
    if allocation.server_id not in (None, server.id):
        raise TransferError("The port on the new node is no longer free.")
    db.execute(
        update(Allocation)
        .where(Allocation.server_id == server.id)
        .values(server_id=None, is_primary=False)
    )
    db.flush()
    allocation.server_id = server.id
    allocation.is_primary = True
    server.node_id = job.target_node_id
    server.status = "offline"
    server.last_error = None
    # Backups that only lived on the old node are gone with it. Copies in the object
    # storage stay and can be restored on the new node.
    for backup in list(db.scalars(select(ServerBackup).where(ServerBackup.server_id == server.id))):
        if backup.local:
            if backup.remote_state == "ok":
                backup.local = False
            else:
                db.delete(backup)
    audit.record(
        db,
        "server.transfer",
        actor_id=job.actor_id,
        target_type="server",
        target_id=str(server.id),
        details={
            "name": server.name,
            "from_node": str(job.source_node_id),
            "to_node": str(job.target_node_id),
            "port": f"{allocation.ip}:{allocation.port}",
        },
    )
    db.commit()


def _fail(db: Session, job: Job, message: str) -> None:
    server = db.get(Server, job.server_id)
    if server is not None and server.status == TRANSFER_STATUS:
        server.status = "offline"
        server.last_error = f"Transfer to another node failed: {message}"[:1024]
    db.commit()


async def run(job: Job) -> None:
    """Runs the whole transfer. Never raises, the result is in job.step and job.error."""
    base = ""
    target_created = False
    try:
        base = _relay_base()
        params = {"name": job.name, "id": str(job.backup_id)}

        # 1. Pack the server on the old node. Nothing is ignored, it is a full copy.
        job.step = "backup"
        await _call(job.source_node_id, "backup.create", {**params, "ignored": ""})
        data = await _wait(job, job.source_node_id, "create", STEP_TIMEOUT["backup"])
        job.size = int(data.get("size") or 0)
        job.sha256 = str(data.get("sha256") or "")
        if job.size <= 0 or not job.sha256:
            raise TransferError("The node did not report the size of the archive.")
        job.parts = max(1, -(-job.size // PART_SIZE))
        if job.parts > MAX_PARTS:
            raise TransferError("The server is too large for a transfer.")
        storage_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
        free = shutil.disk_usage(storage_dir()).free
        if free < job.size + 512 * 1024 * 1024:
            raise TransferError(
                f"Not enough free space on the panel for the archive ({job.size // 2**20} MiB)."
            )

        # 2. Upload to the panel.
        job.step = "upload"
        urls = [f"{base}/api/node-transfers/{job.token}/parts/{i}" for i in range(job.parts)]
        await _call(
            job.source_node_id,
            "backup.upload",
            {**params, "part_size": PART_SIZE, "urls": urls},
        )
        await _wait(job, job.source_node_id, "upload", STEP_TIMEOUT["upload"])
        if len(job.received) != job.parts:
            raise TransferError("Not all parts of the archive arrived at the panel.")

        # 3. Create the container on the new node, which also creates the data folder.
        job.step = "prepare"
        with open_session() as db:
            spec = _target_spec(db, job)
        await _quietly(job.target_node_id, "container.remove", {"name": job.name})
        await _call(job.target_node_id, "container.create", spec)
        target_created = True

        # 4. The new node downloads the archive and checks the sum.
        job.step = "download"
        await _call(
            job.target_node_id,
            "backup.fetch",
            {
                **params,
                "url": f"{base}/api/node-transfers/{job.token}/archive",
                "sha256": job.sha256,
            },
        )
        await _wait(job, job.target_node_id, "fetch", STEP_TIMEOUT["download"])

        # 5. Restore it into the data folder.
        job.step = "restore"
        await _call(job.target_node_id, "backup.restore", {**params, "sha256": job.sha256})
        await _wait(job, job.target_node_id, "restore", STEP_TIMEOUT["restore"])

        # 6. Switch the database, then clean up.
        job.step = "finish"
        with open_session() as db:
            local_ids = [
                str(b.id)
                for b in db.scalars(
                    select(ServerBackup).where(
                        ServerBackup.server_id == job.server_id, ServerBackup.local.is_(True)
                    )
                )
            ]
            _switch(db, job)
        await _quietly(job.target_node_id, "backup.delete", params)
        await _quietly(job.source_node_id, "backup.delete", params)
        for backup_id in local_ids:
            await _quietly(job.source_node_id, "backup.delete", {"name": job.name, "id": backup_id})
        await _quietly(job.source_node_id, "container.remove", {"name": job.name})
        job.step = "done"
    except Exception as exc:  # every failure must end the transfer cleanly
        message = str(exc) if isinstance(exc, TransferError) else "Unexpected error."
        if not isinstance(exc, TransferError):
            log.exception("transfer of server %s failed", job.server_id)
        job.error = message
        job.step = "failed"
        params = {"name": job.name, "id": str(job.backup_id)}
        if target_created:
            await _quietly(job.target_node_id, "container.remove", {"name": job.name})
            await _quietly(job.target_node_id, "backup.delete", params)
        await _quietly(job.source_node_id, "backup.delete", params)
        with contextlib.suppress(Exception), open_session() as db:
            _fail(db, job, message)
    finally:
        _by_token.pop(_token_key(job.token), None)
        await asyncio.to_thread(_drop_files, job)


def start(job: Job) -> None:
    """Registers the job and runs it in the background."""
    _jobs[job.server_id] = job
    _by_token[_token_key(job.token)] = job
    task = asyncio.create_task(run(job))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def reset_interrupted() -> None:
    """After a restart of the panel no transfer runs any more. Until the last step the
    database still points to the old node, so the server is simply where it was."""
    with open_session() as db:
        servers = db.scalars(select(Server).where(Server.status == TRANSFER_STATUS)).all()
        for server in servers:
            server.status = "offline"
            server.last_error = "The panel restarted during a transfer to another node."
        db.commit()
    shutil.rmtree(storage_dir(), ignore_errors=True)
