"""Incidents, drills, resident status (I'm safe / need help), SOS, replay and metrics."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from apiflask import APIBlueprint, abort
from flask import Response, request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.security import current_user, login_required, require_device, staff_required
from app.buildings.service import get_building_or_404
from app.db import SessionLocal
from app.incidents.service import (
    active_incident,
    announce_incident,
    compute_metrics,
    incident_dict,
    log_event,
    open_incident,
    set_incident_status,
    set_participant_status,
    sos_dict,
)
from app.live.store import get_store
from app.models import (
    Building,
    BuildingMode,
    Event,
    Incident,
    IncidentParticipant,
    IncidentStatus,
    ParticipantStatus,
    SosRequest,
    User,
)
from app.realtime.emitter import building_room, emit

bp = APIBlueprint("incidents", __name__, tag="incidents")


class IncidentIn(BaseModel):
    kind: str = Field(default="drill", pattern="^(fire|drill)$")
    note: str | None = None


class IncidentStatusIn(BaseModel):
    status: IncidentStatus


class MyStatusIn(BaseModel):
    status: ParticipantStatus


class SosIn(BaseModel):
    kind: str = Field(default="help", pattern="^(help|trapped|medical)$")
    note: str | None = Field(default=None, max_length=500)


def _incident(incident_id: int) -> Incident:
    inc = SessionLocal.get(Incident, incident_id)
    if inc is None:
        abort(404, "Incident not found")
    get_building_or_404(SessionLocal, inc.building_id, current_user().society_id)
    return inc


@bp.post("/buildings/<int:building_id>/incidents")
@staff_required
@bp.input(IncidentIn)
@bp.doc(summary="Start a fire incident or a drill manually; residents are alerted")
def start_incident(building_id: int, json_data: IncidentIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    inc, created = open_incident(SessionLocal, b, json_data.kind, {"source": "manual", "by": current_user().id, "note": json_data.note},
                                 is_simulation=b.mode == BuildingMode.SIMULATION)
    SessionLocal.commit()
    if created:
        announce_incident(SessionLocal, b, inc)
        SessionLocal.commit()
    return incident_dict(inc), 201 if created else 200


@bp.get("/buildings/<int:building_id>/incidents")
@staff_required
def list_incidents(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    rows = SessionLocal.scalars(select(Incident).where(Incident.building_id == b.id).order_by(Incident.id.desc()).limit(100)).all()
    return {"items": [{**incident_dict(i), "metrics": i.metrics} for i in rows]}


@bp.get("/incidents/<int:incident_id>")
@staff_required
def get_incident(incident_id: int):
    inc = _incident(incident_id)
    rows = SessionLocal.execute(
        select(IncidentParticipant, User).outerjoin(User, IncidentParticipant.user_id == User.id).where(IncidentParticipant.incident_id == inc.id)
    ).all()
    participants = [
        {"device_id": p.device_id, "user_id": p.user_id, "name": u.name if u else None, "flat": u.flat if u else None,
         "phone": u.phone if u else None, "stairs_ok": u.stairs_ok if u else True, "status": p.status.value,
         "notified_at": _iso(p.notified_at), "acknowledged_at": _iso(p.acknowledged_at), "safe_at": _iso(p.safe_at),
         "assigned_exit_id": p.assigned_exit_id}
        for p, u in rows
    ]
    metrics = inc.metrics if inc.status in (IncidentStatus.ALL_CLEAR, IncidentStatus.CLOSED) else compute_metrics(SessionLocal, inc)
    return {**incident_dict(inc), "metrics": metrics, "participants": participants}


@bp.post("/incidents/<int:incident_id>/status")
@staff_required
@bp.input(IncidentStatusIn)
@bp.doc(summary="Declare all-clear or close an incident (computes post-incident metrics)")
def change_status(incident_id: int, json_data: IncidentStatusIn):
    inc = _incident(incident_id)
    set_incident_status(SessionLocal, inc, json_data.status, current_user().id)
    SessionLocal.commit()
    b = SessionLocal.get(Building, inc.building_id)
    announce_incident(SessionLocal, b, inc)
    SessionLocal.commit()
    return {**incident_dict(inc), "metrics": inc.metrics}


@bp.get("/incidents/<int:incident_id>/events")
@staff_required
@bp.doc(summary="Event log for replay. Filters: ?types=snapshot,route.assigned&after_id=0&limit=2000")
def events(incident_id: int):
    inc = _incident(incident_id)
    q = select(Event).where(Event.incident_id == inc.id).order_by(Event.id)
    types = request.args.get("types")
    if types:
        q = q.where(Event.type.in_(types.split(",")))
    after = int(request.args.get("after_id", 0))
    if after:
        q = q.where(Event.id > after)
    limit = min(int(request.args.get("limit", 2000)), 10000)
    rows = SessionLocal.scalars(q.limit(limit)).all()
    return {"items": [{"id": e.id, "ts": e.ts.isoformat(), "type": e.type, "payload": e.payload} for e in rows],
            "started_at": _iso(inc.started_at), "ended_at": _iso(inc.ended_at)}


@bp.get("/incidents/<int:incident_id>/export.csv")
@staff_required
def export_csv(incident_id: int):
    inc = _incident(incident_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["event_id", "timestamp", "type", "device_id", "node_id", "status", "reason", "latency_ms", "detail"])
    for e in SessionLocal.scalars(select(Event).where(Event.incident_id == inc.id, Event.type != "snapshot").order_by(Event.id)):
        p = e.payload or {}
        w.writerow([e.id, e.ts.isoformat(), e.type, p.get("device_id"), p.get("node_id"), p.get("status"), p.get("reason"), p.get("latency_ms"),
                    {k: v for k, v in p.items() if k not in {"device_id", "node_id", "status", "reason", "latency_ms", "path"}}])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=incident-{inc.id}.csv"})


# ---------------------------------------------------------------------- residents


def _my_incident() -> tuple[Building, Incident]:
    user = current_user()
    if user.building_id is None:
        abort(409, "Your account is not linked to a building")
    b = SessionLocal.get(Building, user.building_id)
    inc = active_incident(SessionLocal, b.id)
    if inc is None:
        abort(409, "There is no active incident")
    return b, inc


@bp.get("/me/incident")
@login_required()
@bp.doc(summary="The active incident for the resident's building, if any")
def my_incident():
    user = current_user()
    if user.building_id is None:
        return {"incident": None}
    b = SessionLocal.get(Building, user.building_id)
    inc = active_incident(SessionLocal, b.id)
    status = None
    if inc is not None and request.headers.get("Authorization"):
        from flask import g

        if g.get("device_id"):
            p = SessionLocal.scalars(select(IncidentParticipant).where(IncidentParticipant.incident_id == inc.id,
                                                                        IncidentParticipant.device_id == g.device_id)).first()
            status = p.status.value if p else "unknown"
    snap = get_store().get_snapshot(b.id) or {}
    return {
        "incident": incident_dict(inc),
        "my_status": status,
        "building": {"id": b.id, "name": b.name, "mode": b.mode.value, "graph_version": b.graph_version, "hazard_version": b.hazard_version},
        "hazards": snap.get("hazards", {}),
    }


@bp.post("/me/status")
@login_required()
@bp.input(MyStatusIn)
@bp.doc(summary="Resident reports evacuating / safe / needs help")
def my_status(json_data: MyStatusIn):
    device_id = require_device()
    b, inc = _my_incident()
    user = current_user()
    p = set_participant_status(SessionLocal, inc, device_id, user.id, json_data.status)
    SessionLocal.commit()
    get_store().push_inbox({"type": "status", "device_id": device_id, "building_id": b.id, "status": p.status.value})
    emit("participant.updated", {"device_id": device_id, "user_id": user.id, "name": user.name, "flat": user.flat, "status": p.status.value},
         building_room(b.id))
    return {"status": p.status.value, "safe_at": _iso(p.safe_at)}


@bp.post("/me/acknowledge")
@login_required()
@bp.doc(summary="Resident opened the alarm (measures alert-to-acknowledge time)")
def acknowledge():
    device_id = require_device()
    b, inc = _my_incident()
    p = set_participant_status(SessionLocal, inc, device_id, current_user().id, ParticipantStatus.EVACUATING)
    SessionLocal.commit()
    get_store().push_inbox({"type": "status", "device_id": device_id, "building_id": b.id, "status": p.status.value})
    return {"status": p.status.value}


@bp.post("/sos")
@login_required()
@bp.input(SosIn)
@bp.doc(summary="Need help / trapped. Uses the device's latest position")
def create_sos(json_data: SosIn):
    device_id = require_device()
    b, inc = _my_incident()
    user = current_user()
    state = get_store().get_device(device_id) or {}
    fix = state.get("fix") or {}
    sos = SosRequest(building_id=b.id, incident_id=inc.id, device_id=device_id, user_id=user.id, kind=json_data.kind, note=json_data.note,
                     node_id=fix.get("node_id"), x=fix.get("x"), y=fix.get("y"), level=fix.get("level"))
    SessionLocal.add(sos)
    set_participant_status(SessionLocal, inc, device_id, user.id, ParticipantStatus.NEEDS_HELP)
    SessionLocal.flush()
    log_event(SessionLocal, b.id, inc.id, "sos.created", sos_dict(sos, user))
    SessionLocal.commit()
    get_store().push_inbox({"type": "status", "device_id": device_id, "building_id": b.id, "status": "needs_help"})
    emit("sos.created", sos_dict(sos, user), building_room(b.id))
    return sos_dict(sos, user), 201


@bp.get("/buildings/<int:building_id>/sos")
@staff_required
def list_sos(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    q = select(SosRequest, User).outerjoin(User, SosRequest.user_id == User.id).where(SosRequest.building_id == b.id)
    if request.args.get("open") == "1":
        q = q.where(SosRequest.resolved_at.is_(None))
    rows = SessionLocal.execute(q.order_by(SosRequest.id.desc()).limit(200)).all()
    return {"items": [sos_dict(s, u) for s, u in rows]}


@bp.post("/sos/<int:sos_id>/resolve")
@staff_required
def resolve_sos(sos_id: int):
    sos = SessionLocal.get(SosRequest, sos_id)
    if sos is None:
        abort(404)
    get_building_or_404(SessionLocal, sos.building_id, current_user().society_id)
    sos.resolved_at = datetime.now(UTC)
    sos.resolved_by = current_user().id
    log_event(SessionLocal, sos.building_id, sos.incident_id, "sos.resolved", {"sos_id": sos.id, "by": current_user().id})
    SessionLocal.commit()
    emit("sos.resolved", {"id": sos.id}, building_room(sos.building_id))
    return sos_dict(sos)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
