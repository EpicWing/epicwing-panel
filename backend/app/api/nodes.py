import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Node
from app.schemas.node import EnrollmentOut, NodeCreate, NodeCreated, NodeOut
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit
from app.services import nodes as node_service

router = APIRouter(prefix="/nodes", tags=["nodes"])

ManageNodes = Annotated[AuthContext, Depends(require(Permission.NODES_MANAGE))]


def _name_taken() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "A node with this name already exists.")


@router.get("")
def list_nodes(
    _auth: ManageNodes, db: Annotated[Session, Depends(get_db)]
) -> list[NodeOut]:
    nodes = db.scalars(select(Node).order_by(Node.created_at))
    return [NodeOut.model_validate(n) for n in nodes]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_node(
    body: NodeCreate,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> NodeCreated:
    if db.scalar(select(Node.id).where(func.lower(Node.name) == body.name.lower())):
        raise _name_taken()

    node = Node(
        name=body.name,
        location=body.location,
        fqdn=body.fqdn,
        port_range_start=body.port_range_start,
        port_range_end=body.port_range_end,
    )
    db.add(node)
    try:
        db.flush()
        token, enrollment = node_service.create_enrollment(db, node, auth.user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None

    # Der Token gehört nicht ins Audit-Log.
    audit.record(
        db,
        "node.create",
        actor_id=auth.user.id,
        target_type="node",
        target_id=str(node.id),
        ip=audit.client_ip(request),
        details={"name": node.name},
    )
    return NodeCreated(
        node=NodeOut.model_validate(node),
        enrollment=EnrollmentOut(token=token, expires_at=enrollment.expires_at),
    )


@router.post("/{node_id}/enrollment", status_code=status.HTTP_201_CREATED)
def new_enrollment(
    node_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> EnrollmentOut:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    if node.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This node is already registered.")

    token, enrollment = node_service.create_enrollment(db, node, auth.user.id)
    db.commit()
    audit.record(
        db,
        "node.enrollment_create",
        actor_id=auth.user.id,
        target_type="node",
        target_id=str(node.id),
        ip=audit.client_ip(request),
        details={"name": node.name},
    )
    return EnrollmentOut(token=token, expires_at=enrollment.expires_at)
