"""Incident lifecycle, participants, event log and post-incident metrics (paper §IV-4:
"once the evacuation is successfully completed, the system logs post-incident data")."""

from __future__ import annotations

import logging
import statistics
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Building,
    Device,
    Event,
    Incident,
    IncidentParticipant,
    IncidentStatus,
    ParticipantStatus,
    Role,
    SosRequest,
    User,
    UserStatus,
    utcnow,
)
from app.notifications import fcm
from app.realtime.emitter import building_room, emit, residents_room

log = logging.getLogger(__name__)

ACTIVE = (IncidentStatus.DETECTED, IncidentStatus.EVACUATING)


def log_event(session: Session, building_id: int, incident_id: int | None, type_: str, payload: dict) -> Event:
    ev = Event(building_id=building_id, incident_id=incident_id, type=type_, payload=payload, ts=utcnow())
    session.add(ev)
    return ev


def active_incident(session: Session, building_id: int) -> Incident | None:
    return session.scalars(
        select(Incident).where(Incident.building_id == building_id, Incident.status.in_(ACTIVE)).order_by(Incident.id.desc())
    ).first()


def incident_dict(inc: Incident | None) -> dict | None:
    if inc is None:
        return None
    return {
        "id": inc.id,
        "building_id": inc.building_id,
        "kind": inc.kind,
        "status": inc.status.value,
        "is_simulation": inc.is_simulation,
        "trigger": inc.trigger,
        "started_at": inc.started_at.isoformat() if inc.started_at else None,
        "ended_at": inc.ended_at.isoformat() if inc.ended_at else None,
    }


def building_resident_devices(session: Session, building_id: int) -> list[tuple[Device, User]]:
    rows = session.execute(
        select(Device, User)
        .join(User, Device.user_id == User.id)
        .where(User.building_id == building_id, User.status == UserStatus.APPROVED, User.role.in_([Role.RESIDENT, Role.SURVEYOR]))
    ).all()
    return [(d, u) for d, u in rows]


def open_incident(session: Session, building: Building, kind: str, trigger: dict, is_simulation: bool = False) -> tuple[Incident, bool]:
    existing = active_incident(session, building.id)
    if existing is not None:
        return existing, False
    inc = Incident(
        building_id=building.id,
        kind=kind,
        status=IncidentStatus.EVACUATING,
        is_simulation=is_simulation,
        trigger=trigger,
        started_at=utcnow(),
    )
    session.add(inc)
    session.flush()
    for device, user in building_resident_devices(session, building.id):
        session.add(IncidentParticipant(incident_id=inc.id, device_id=device.id, user_id=user.id, status=ParticipantStatus.UNKNOWN))
    log_event(session, building.id, inc.id, "incident.opened", {"kind": kind, "trigger": trigger, "is_simulation": is_simulation})
    return inc, True


def announce_incident(session: Session, building: Building, inc: Incident) -> None:
    """After commit: socket broadcast + FCM push to every resident device of the building."""
    data = {"incident": incident_dict(inc), "building_id": building.id, "building_name": building.name}
    emit("incident.updated", data, building_room(building.id))
    emit("incident.updated", data, residents_room(building.id))
    if inc.status not in ACTIVE:
        title, body = f"All clear - {building.name}", "The incident is over. Follow instructions from rescuers."
    elif inc.kind == "drill":
        title, body = f"Fire DRILL - {building.name}", "This is a drill. Open the app and follow the evacuation route."
    else:
        title, body = f"FIRE - evacuate {building.name} now", "Open the app for your safest route out."
    devices = building_resident_devices(session, building.id)
    result = fcm.send_alarm(
        [d.fcm_token for d, _ in devices if d.fcm_token],
        {"type": "incident", "incident_id": str(inc.id), "building_id": str(building.id), "kind": inc.kind, "status": inc.status.value},
        title,
        body,
    )
    if result.get("invalid_tokens"):
        for d, _ in devices:
            if d.fcm_token in result["invalid_tokens"]:
                d.fcm_token = None
    now = utcnow()
    if inc.status in ACTIVE:
        for p in session.scalars(select(IncidentParticipant).where(IncidentParticipant.incident_id == inc.id)):
            p.notified_at = p.notified_at or now
    log_event(session, building.id, inc.id, "notification.sent", {"title": title, **{k: v for k, v in result.items() if k != "invalid_tokens"}})


def set_incident_status(session: Session, inc: Incident, status: IncidentStatus, by_user_id: int | None = None) -> None:
    inc.status = status
    if status in (IncidentStatus.ALL_CLEAR, IncidentStatus.CLOSED) and inc.ended_at is None:
        inc.ended_at = utcnow()
    if status == IncidentStatus.CLOSED or status == IncidentStatus.ALL_CLEAR:
        inc.metrics = compute_metrics(session, inc)
    log_event(session, inc.building_id, inc.id, "incident.status", {"status": status.value, "by": by_user_id})


def ensure_participant(session: Session, inc: Incident, device_id: str, user_id: int | None) -> IncidentParticipant:
    p = session.scalars(
        select(IncidentParticipant).where(IncidentParticipant.incident_id == inc.id, IncidentParticipant.device_id == device_id)
    ).first()
    if p is None:
        p = IncidentParticipant(incident_id=inc.id, device_id=device_id, user_id=user_id, status=ParticipantStatus.UNKNOWN)
        session.add(p)
        session.flush()
    return p


def set_participant_status(session: Session, inc: Incident, device_id: str, user_id: int | None, status: ParticipantStatus) -> IncidentParticipant:
    p = ensure_participant(session, inc, device_id, user_id)
    p.status = status
    now = utcnow()
    if status == ParticipantStatus.SAFE:
        p.safe_at = p.safe_at or now
    if status in (ParticipantStatus.EVACUATING, ParticipantStatus.SAFE, ParticipantStatus.NEEDS_HELP):
        p.acknowledged_at = p.acknowledged_at or now
    log_event(session, inc.building_id, inc.id, "participant.status", {"device_id": device_id, "user_id": user_id, "status": status.value})
    return p


def sos_dict(s: SosRequest, user: User | None = None) -> dict:
    return {
        "id": s.id,
        "building_id": s.building_id,
        "incident_id": s.incident_id,
        "device_id": s.device_id,
        "user_id": s.user_id,
        "user_name": user.name if user else None,
        "flat": user.flat if user else None,
        "phone": user.phone if user else None,
        "stairs_ok": user.stairs_ok if user else True,
        "kind": s.kind,
        "note": s.note,
        "node_id": s.node_id,
        "x": s.x,
        "y": s.y,
        "level": s.level,
        "created_at": s.created_at.isoformat(),
        "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
    }


def _seconds(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=b.tzinfo)
    if b.tzinfo is None:
        b = b.replace(tzinfo=a.tzinfo)
    return (b - a).total_seconds()


def compute_metrics(session: Session, inc: Incident) -> dict:
    participants = session.scalars(select(IncidentParticipant).where(IncidentParticipant.incident_id == inc.id)).all()
    evac_times = [t for p in participants if (t := _seconds(inc.started_at, p.safe_at)) is not None]
    ack_times = [t for p in participants if (t := _seconds(inc.started_at, p.acknowledged_at)) is not None]
    route_events = session.scalars(
        select(Event).where(Event.incident_id == inc.id, Event.type == "route.assigned")
    ).all()
    latencies = [e.payload.get("latency_ms") for e in route_events if e.payload.get("latency_ms") is not None]
    reasons: dict[str, int] = {}
    for e in route_events:
        r = e.payload.get("reason", "initial")
        reasons[r] = reasons.get(r, 0) + 1
    sim_summary = session.scalars(
        select(Event).where(Event.incident_id == inc.id, Event.type == "sim.summary").order_by(Event.id.desc())
    ).first()
    status_counts: dict[str, int] = {}
    for p in participants:
        status_counts[p.status.value] = status_counts.get(p.status.value, 0) + 1
    return {
        "duration_s": _seconds(inc.started_at, inc.ended_at or utcnow()),
        "residents": len(participants),
        "status_counts": status_counts,
        "avg_evac_time_s": round(statistics.mean(evac_times), 1) if evac_times else None,
        "max_evac_time_s": round(max(evac_times), 1) if evac_times else None,
        "avg_ack_time_s": round(statistics.mean(ack_times), 1) if ack_times else None,
        "route_assignments": len(route_events),
        "reroutes_by_reason": reasons,
        "avg_route_update_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "p95_route_update_latency_ms": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1) if latencies else None,
        "simulation": sim_summary.payload if sim_summary else None,
    }
