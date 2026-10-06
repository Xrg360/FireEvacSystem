"""Dynamic digital signage (paper §III-E). Displays authenticate with a per-sign token."""

from __future__ import annotations

from apiflask import APIBlueprint, abort
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.security import admin_required, current_user, new_token, staff_required
from app.buildings.service import get_building_or_404
from app.db import SessionLocal
from app.live.store import get_store
from app.models import Building, Node, Signage

bp = APIBlueprint("signage", __name__, tag="signage")


class SignageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    node_id: int


def signage_dict(s: Signage, node: Node | None = None, with_token: bool = False) -> dict:
    out = {"id": s.id, "building_id": s.building_id, "node_id": s.node_id, "node_name": node.name if node else None, "name": s.name}
    if with_token:
        out["token"] = s.token
    return out


@bp.get("/buildings/<int:building_id>/signage")
@staff_required
def list_signage(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    rows = SessionLocal.execute(select(Signage, Node).join(Node, Signage.node_id == Node.id).where(Signage.building_id == b.id)).all()
    is_admin = current_user().role.value == "society_admin"
    return {"items": [signage_dict(s, n, with_token=is_admin) for s, n in rows]}


@bp.post("/buildings/<int:building_id>/signage")
@admin_required
@bp.input(SignageIn)
def create_signage(building_id: int, json_data: SignageIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    node = SessionLocal.get(Node, json_data.node_id)
    if node is None or node.building_id != b.id:
        abort(422, "Node is not in this building")
    s = Signage(building_id=b.id, node_id=node.id, name=json_data.name, token=new_token(18))
    SessionLocal.add(s)
    b.graph_version += 1  # engine reloads its signage list with the graph
    SessionLocal.commit()
    return signage_dict(s, node, with_token=True), 201


@bp.delete("/signage/<int:signage_id>")
@admin_required
def delete_signage(signage_id: int):
    s = SessionLocal.get(Signage, signage_id)
    if s is None:
        abort(404)
    b = get_building_or_404(SessionLocal, s.building_id, current_user().society_id)
    SessionLocal.delete(s)
    b.graph_version += 1
    SessionLocal.commit()
    return "", 204


@bp.get("/signage/display/<token>")
@bp.doc(summary="Current state for a display (token in the URL; no login)", security=[])
def display(token: str):
    s = SessionLocal.scalars(select(Signage).where(Signage.token == token)).first()
    if s is None:
        abort(404, "Unknown display")
    b = SessionLocal.get(Building, s.building_id)
    node = SessionLocal.get(Node, s.node_id)
    state = get_store().get_json(f"signage:{s.id}") or {"status": "normal", "message": "Waiting for the evacuation server...", "arrow_deg": None}
    return {"signage": signage_dict(s, node), "building": {"id": b.id, "name": b.name}, "state": state}
