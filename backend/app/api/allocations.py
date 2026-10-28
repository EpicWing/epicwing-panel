import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Allocation, Node, Server
from app.schemas.server import AllocationCreate, AllocationOut
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit

router = APIRouter(tags=["allocations"])

ManageNodes = Annotated[AuthContext, Depends(require(Permission.NODES_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]


def _get_node(db: Session, node_id: uuid.UUID) -> Node:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    return node


@router.get("/nodes/{node_id}/allocations")
def list_allocations(
    node_id: uuid.UUID, _auth: ManageNodes, db: DbSession
) -> list[AllocationOut]:
    _get_node(db, node_id)
    rows = db.execute(
        select(Allocation, Server.name)
        .outerjoin(Server, Server.id == Allocation.server_id)
        .where(Allocation.node_id == node_id)
        .order_by(Allocation.port, Allocation.ip)
    ).all()
    outs = []
    for allocation, server_name in rows:
        out = AllocationOut.model_validate(allocation)
        out.server_name = server_name
        outs.append(out)
    return outs


@router.post("/nodes/{node_id}/allocations", status_code=status.HTTP_201_CREATED)
def create_allocations(
    node_id: uuid.UUID,
    body: AllocationCreate,
    request: Request,
    auth: ManageNodes,
    db: DbSession,
) -> list[AllocationOut]:
    node = _get_node(db, node_id)
    first = body.port_start
    last = body.port_end if body.port_end is not None else first
    if first < 1024 or last > 65535:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ports must be between 1024 and 65535.",
        )
    taken = db.scalar(
        select(Allocation.port)
        .where(
            Allocation.node_id == node.id,
            Allocation.ip == body.ip,
            Allocation.port.between(first, last),
        )
        .order_by(Allocation.port)
        .limit(1)
    )
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Port {taken} already exists on this IP.")

    rows = [Allocation(node_id=node.id, ip=body.ip, port=port) for port in range(first, last + 1)]
    db.add_all(rows)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Some of these ports already exist."
        ) from None
    audit.record(
        db,
        "allocation.create",
        actor_id=auth.user.id,
        target_type="node",
        target_id=str(node.id),
        ip=audit.client_ip(request),
        details={"node": node.name, "ip": body.ip, "first": first, "last": last},
    )
    return [AllocationOut.model_validate(r) for r in rows]


@router.delete("/allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation(
    allocation_id: uuid.UUID, request: Request, auth: ManageNodes, db: DbSession
) -> None:
    allocation = db.get(Allocation, allocation_id)
    if allocation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Allocation not found.")
    if allocation.server_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This allocation is assigned to a server."
        )
    details = {"node_id": str(allocation.node_id), "ip": allocation.ip, "port": allocation.port}
    db.delete(allocation)
    db.commit()
    audit.record(
        db,
        "allocation.delete",
        actor_id=auth.user.id,
        target_type="allocation",
        target_id=str(allocation_id),
        ip=audit.client_ip(request),
        details=details,
    )
