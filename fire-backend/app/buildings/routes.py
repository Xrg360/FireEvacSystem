"""Buildings, floors and the evacuation graph (dashboard editor + app offline cache)."""

from __future__ import annotations

import uuid
from pathlib import Path

from apiflask import APIBlueprint, abort
from flask import current_app, request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.security import admin_required, current_user, login_required
from app.buildings.service import get_building_or_404, graph_dict, replace_graph
from app.db import SessionLocal
from app.incidents.service import active_incident, incident_dict
from app.live.store import get_store
from app.models import DEFAULT_BUILDING_SETTINGS, Building, BuildingMode, Floor, Role
from app.routing.graph import BuildingGraph, validate_graph

bp = APIBlueprint("buildings", __name__, tag="buildings")

ALLOWED_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


class BuildingIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    floor_height_m: float = 3.0


class BuildingPatch(BaseModel):
    name: str | None = None
    mode: BuildingMode | None = None
    floor_height_m: float | None = None
    footprint: list[list[float]] | None = None
    settings: dict | None = None


class GraphIn(BaseModel):
    building: dict = Field(default_factory=dict)
    floors: list[dict]
    nodes: list[dict]
    edges: list[dict]
    access_points: list[dict] = Field(default_factory=list)


def building_dict(b: Building, with_incident: bool = True) -> dict:
    out = {
        "id": b.id,
        "society_id": b.society_id,
        "name": b.name,
        "mode": b.mode.value,
        "floor_height_m": b.floor_height_m,
        "graph_version": b.graph_version,
        "hazard_version": b.hazard_version,
        "footprint": b.footprint,
        "settings": {**DEFAULT_BUILDING_SETTINGS, **(b.settings or {})},
    }
    if with_incident:
        out["incident"] = incident_dict(active_incident(SessionLocal, b.id))
    return out


def _building(building_id: int) -> Building:
    return get_building_or_404(SessionLocal, building_id, current_user().society_id)


@bp.get("/buildings")
@login_required()
def list_buildings():
    rows = SessionLocal.scalars(select(Building).where(Building.society_id == current_user().society_id).order_by(Building.id)).all()
    return {"items": [building_dict(b) for b in rows]}


@bp.post("/buildings")
@admin_required
@bp.input(BuildingIn)
def create_building(json_data: BuildingIn):
    b = Building(society_id=current_user().society_id, name=json_data.name, floor_height_m=json_data.floor_height_m,
                 settings=dict(DEFAULT_BUILDING_SETTINGS))
    SessionLocal.add(b)
    SessionLocal.flush()
    SessionLocal.add(Floor(building_id=b.id, level=0, name="Ground Floor"))
    SessionLocal.commit()
    return building_dict(b), 201


@bp.get("/buildings/<int:building_id>")
@login_required()
def get_building(building_id: int):
    return building_dict(_building(building_id))


@bp.patch("/buildings/<int:building_id>")
@admin_required
@bp.input(BuildingPatch)
@bp.doc(summary="Rename, switch Live/Simulation mode, set footprint or routing/positioning settings")
def patch_building(building_id: int, json_data: BuildingPatch):
    b = _building(building_id)
    data = json_data.model_dump(exclude_unset=True)
    if "settings" in data and data["settings"] is not None:
        unknown = set(data["settings"]) - set(DEFAULT_BUILDING_SETTINGS)
        if unknown:
            abort(422, f"Unknown settings: {sorted(unknown)}")
        b.settings = {**DEFAULT_BUILDING_SETTINGS, **(b.settings or {}), **data.pop("settings")}
    if data.get("mode") == BuildingMode.LIVE and b.mode == BuildingMode.SIMULATION:
        get_store().push_inbox({"type": "sim", "building_id": b.id, "action": "stop"})
    for k, v in data.items():
        setattr(b, k, v)
    SessionLocal.commit()
    return building_dict(b)


@bp.delete("/buildings/<int:building_id>")
@admin_required
def delete_building(building_id: int):
    b = _building(building_id)
    SessionLocal.delete(b)
    SessionLocal.commit()
    return "", 204


@bp.get("/buildings/<int:building_id>/graph")
@login_required()
@bp.doc(summary="Floors, nodes, edges and access points (fixture format). Apps cache this for offline routing")
def get_graph(building_id: int):
    return graph_dict(SessionLocal, _building(building_id))


@bp.put("/buildings/<int:building_id>/graph")
@admin_required
@bp.input(GraphIn)
@bp.doc(summary="Publish an edited graph; bumps graph_version. 422 with problems if invalid")
def put_graph(building_id: int, json_data: GraphIn):
    b = _building(building_id)
    problems = replace_graph(SessionLocal, b, json_data.model_dump())
    if problems:
        SessionLocal.rollback()
        abort(422, "Graph is not valid", detail={"problems": problems})
    SessionLocal.commit()
    return graph_dict(SessionLocal, b)


@bp.post("/buildings/<int:building_id>/graph/validate")
@login_required({Role.SOCIETY_ADMIN, Role.SURVEYOR})
@bp.input(GraphIn)
def validate(building_id: int, json_data: GraphIn):
    _building(building_id)
    data = json_data.model_dump()
    try:
        graph = BuildingGraph.from_dict({**data, "building": {"id": building_id, "name": "draft", **data.get("building", {})}})
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "problems": [f"Malformed graph: {exc}"]}
    problems = validate_graph(graph)
    return {"ok": not problems, "problems": problems}


@bp.post("/floors/<int:floor_id>/plan")
@admin_required
@bp.doc(summary="Upload a floor-plan image (multipart field `file`); optional form field scale_px_per_m")
def upload_plan(floor_id: int):
    floor = SessionLocal.get(Floor, floor_id)
    if floor is None:
        abort(404, "Floor not found")
    _building(floor.building_id)
    f = request.files.get("file")
    if f is None or not f.filename:
        abort(422, "Missing file")
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE:
        abort(422, f"Unsupported image type {ext}")
    cfg = current_app.config["FIRE"]
    name = f"floor-{floor.id}-{uuid.uuid4().hex[:8]}{ext}"
    f.save(cfg.upload_dir / name)
    floor.plan_image = f"/uploads/{name}"
    scale = request.form.get("scale_px_per_m")
    if scale:
        floor.scale_px_per_m = float(scale)
    b = SessionLocal.get(Building, floor.building_id)
    b.graph_version += 1
    SessionLocal.commit()
    return {"id": floor.id, "plan_image": floor.plan_image, "scale_px_per_m": floor.scale_px_per_m}


@bp.get("/buildings/<int:building_id>/live")
@login_required({Role.SOCIETY_ADMIN, Role.RESCUER})
@bp.doc(summary="Latest live snapshot (same payload as the `snapshot` socket event)")
def live(building_id: int):
    _building(building_id)
    snap = get_store().get_snapshot(building_id)
    return snap or {"building_id": building_id, "stale": True}
