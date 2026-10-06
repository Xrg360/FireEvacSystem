"""Positioning input from phones (REST fallback for the socket) and survey mode."""

from __future__ import annotations

import math
import time

from apiflask import APIBlueprint, abort
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.security import current_user, login_required, require_device
from app.buildings.service import get_building_or_404, load_graph
from app.db import SessionLocal
from app.incidents.service import active_incident
from app.live.store import get_store
from app.models import AccessPoint, Building, BuildingMode, FingerprintSample, Node, Role
from app.positioning import fingerprint as fp
from app.positioning.rssi import fit_path_loss

bp = APIBlueprint("positioning", __name__, tag="positioning")

SURVEY_ROLES = {Role.SURVEYOR, Role.SOCIETY_ADMIN}


class Reading(BaseModel):
    bssid: str = Field(pattern=r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
    rssi: float = Field(ge=-120, le=0)
    ssid: str | None = None
    frequency: int | None = None


class ScanIn(BaseModel):
    readings: list[Reading] = Field(max_length=200)
    ts: float | None = None


class GpsIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0, le=5000)


class ManualIn(BaseModel):
    node_id: int


class FloorConfirmIn(BaseModel):
    level: int


class SurveyIn(BaseModel):
    node_id: int
    readings: list[Reading] = Field(min_length=1, max_length=200)


class RegisterApIn(BaseModel):
    bssid: str = Field(pattern=r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
    ssid: str | None = None
    node_id: int | None = Field(default=None, description="Stand next to the router at this node")
    floor_id: int | None = None
    x: float | None = None
    y: float | None = None


def tracking_building() -> Building:
    """Phones only report positions during an incident/drill or in simulation mode (privacy)."""
    user = current_user()
    if user.building_id is None:
        abort(409, "Your account is not linked to a building yet")
    b = SessionLocal.get(Building, user.building_id)
    if b.mode != BuildingMode.SIMULATION and active_incident(SessionLocal, b.id) is None:
        abort(409, "Location tracking is only active during an incident or drill", detail={"tracking": False})
    return b


def _push(kind: str, **data) -> dict:
    device_id = require_device()
    b = tracking_building()
    get_store().push_inbox({"type": kind, "device_id": device_id, "building_id": b.id, "received": time.time(), **data})
    return {"accepted": True}


@bp.post("/positioning/scan")
@login_required()
@bp.input(ScanIn)
@bp.doc(summary="Wi-Fi scan (BSSID + RSSI). Prefer the socket `scan` event; this is the fallback")
def scan(json_data: ScanIn):
    return _push("scan", readings=[r.model_dump() for r in json_data.readings])


@bp.post("/positioning/gps")
@login_required()
@bp.input(GpsIn)
def gps(json_data: GpsIn):
    return _push("gps", **json_data.model_dump())


@bp.post("/positioning/manual")
@login_required()
@bp.input(ManualIn)
@bp.doc(summary="'Where are you?' picker result - a strong observation")
def manual(json_data: ManualIn):
    node = SessionLocal.get(Node, json_data.node_id)
    if node is None or node.building_id != current_user().building_id:
        abort(422, "Unknown location")
    return _push("manual", node_id=node.id)


@bp.post("/positioning/floor-confirm")
@login_required()
@bp.input(FloorConfirmIn)
def floor_confirm(json_data: FloorConfirmIn):
    return _push("floor_confirm", level=json_data.level)


@bp.get("/positioning/me")
@login_required()
@bp.doc(summary="Latest fix and route for this device (used after reconnecting)")
def me():
    device_id = require_device()
    return get_store().get_device(device_id) or {"fix": None, "route": None}


# ---------------------------------------------------------------------- survey mode


@bp.post("/buildings/<int:building_id>/survey")
@login_required(SURVEY_ROLES)
@bp.input(SurveyIn)
@bp.doc(summary="Record one labelled Wi-Fi scan taken at a known node")
def survey(building_id: int, json_data: SurveyIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    node = SessionLocal.get(Node, json_data.node_id)
    if node is None or node.building_id != b.id:
        abort(422, "Node is not in this building")
    readings = {r.bssid.lower(): r.rssi for r in json_data.readings}
    SessionLocal.add(FingerprintSample(building_id=b.id, node_id=node.id, device_id=None, readings=readings))
    SessionLocal.commit()
    count = SessionLocal.scalar(select(func.count(FingerprintSample.id)).where(FingerprintSample.node_id == node.id))
    return {"node_id": node.id, "samples_at_node": count}


@bp.get("/buildings/<int:building_id>/survey/coverage")
@login_required({*SURVEY_ROLES, Role.RESCUER})
def coverage(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    rows = SessionLocal.execute(
        select(FingerprintSample.node_id, func.count(FingerprintSample.id)).where(FingerprintSample.building_id == b.id).group_by(FingerprintSample.node_id)
    ).all()
    counts = dict(rows)
    nodes = SessionLocal.scalars(select(Node).where(Node.building_id == b.id)).all()
    return {
        "recommended_per_node": 20,
        "nodes": [{"node_id": n.id, "name": n.name, "floor_id": n.floor_id, "samples": counts.get(n.id, 0)} for n in nodes if n.type.value != "assembly"],
    }


@bp.delete("/buildings/<int:building_id>/survey/<int:node_id>")
@login_required(SURVEY_ROLES)
def clear_node_samples(building_id: int, node_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    rows = SessionLocal.scalars(select(FingerprintSample).where(FingerprintSample.building_id == b.id, FingerprintSample.node_id == node_id)).all()
    for r in rows:
        SessionLocal.delete(r)
    SessionLocal.commit()
    get_store().push_inbox({"type": "retrain", "building_id": b.id})
    return {"deleted": len(rows)}


@bp.post("/buildings/<int:building_id>/access-points/register")
@login_required(SURVEY_ROLES)
@bp.input(RegisterApIn)
@bp.doc(summary="Register a router position (stand next to it and pick the node, or give x/y)")
def register_ap(building_id: int, json_data: RegisterApIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    if json_data.node_id is not None:
        node = SessionLocal.get(Node, json_data.node_id)
        if node is None or node.building_id != b.id:
            abort(422, "Unknown node")
        floor_id, x, y = node.floor_id, node.x, node.y
    elif json_data.floor_id is not None and json_data.x is not None and json_data.y is not None:
        floor_id, x, y = json_data.floor_id, json_data.x, json_data.y
    else:
        abort(422, "Give node_id, or floor_id + x + y")
    bssid = json_data.bssid.lower()
    ap = SessionLocal.scalars(select(AccessPoint).where(AccessPoint.building_id == b.id, AccessPoint.bssid == bssid)).first()
    if ap is None:
        ap = AccessPoint(building_id=b.id, bssid=bssid)
        SessionLocal.add(ap)
    ap.ssid, ap.floor_id, ap.x, ap.y, ap.enabled = json_data.ssid, floor_id, x, y, True
    b.graph_version += 1
    SessionLocal.commit()
    return {"id": ap.id, "bssid": ap.bssid, "floor_id": ap.floor_id, "x": ap.x, "y": ap.y}


@bp.post("/buildings/<int:building_id>/survey/calibrate")
@login_required(SURVEY_ROLES)
@bp.doc(summary="Fit P_ref and path-loss exponent per router (eq. 1) from survey data and evaluate the fingerprint model")
def calibrate(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    graph = load_graph(SessionLocal, b)
    samples = SessionLocal.scalars(select(FingerprintSample).where(FingerprintSample.building_id == b.id)).all()
    aps = SessionLocal.scalars(select(AccessPoint).where(AccessPoint.building_id == b.id)).all()
    results = []
    for ap in aps:
        dists, rssis = [], []
        ap_level = next((f.level for f in graph.floors.values() if f.id == ap.floor_id), 0)
        for s in samples:
            if ap.bssid in s.readings and s.node_id in graph.nodes:
                n = graph.nodes[s.node_id]
                if n.level != ap_level:
                    continue  # same-floor samples only; slabs are handled by floor attenuation
                dists.append(math.hypot(n.x - ap.x, n.y - ap.y))
                rssis.append(float(s.readings[ap.bssid]))
        fit = fit_path_loss(dists, rssis)
        if fit is not None:
            ap.p_ref, ap.eta = round(fit[0], 2), round(fit[1], 3)
            ap.calibrated = True
        results.append({"bssid": ap.bssid, "samples": len(dists), "p_ref": ap.p_ref, "eta": ap.eta, "calibrated": fit is not None})
    b.graph_version += 1
    SessionLocal.commit()
    node_xy = {nid: (n.x, n.y, n.level) for nid, n in graph.nodes.items()}
    cv = fp.cross_validate([(s.node_id, s.readings) for s in samples if s.node_id in graph.nodes], node_xy)
    get_store().push_inbox({"type": "retrain", "building_id": b.id})
    return {"access_points": results, "fingerprint_cross_validation": cv}
