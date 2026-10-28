"""Panel: öffentlicher, fester Name, nicht änderbar."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["panel"])

PANEL_NAME = "EpicWing"


class PanelInfo(BaseModel):
    name: str


@router.get("/panel")
def panel_info() -> PanelInfo:
    return PanelInfo(name=PANEL_NAME)
