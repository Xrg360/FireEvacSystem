"""Sensor registry, reading ingest (HTTP; MQTT bridges into the same function) and hazards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apiflask import APIBlueprint, abort
from flask import request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import (
    admin_required,
    current_user,
    hash_secret,
    new_token,
    secrets_match,
    staff_required,
)
from app.buildings.service import get_building_or_404
from app.db import SessionLocal
from app.incidents.service import announce_incident, log_event, open_incident
from app.models import (
    DEFAULT_BUILDING_SETTINGS,
    Building,
    HazardLevel,
    Node,
    NodeHazard,
    Sensor,
    SensorReading,
    SensorType,
)
from app.realtime.emitter import building_room, emit
from app.sensors.detection import evaluate
from app.sensors.hazards import clear_hazards, set_hazard

bp = APIBlueprint("sensors", __name__, tag="sensors")


class SensorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: SensorType = SensorType.MULTI
    node_id: int


class ReadingIn(BaseModel):
    smoke: float | None = Field(default=None, ge=0)
    temperature_c: float | None = Field(default=None, ge=-50, le=1500)
    flame: bool | None = None
    alarm: bool | None = None


class HazardIn(BaseModel):
    node_id: int
    level: HazardLevel


def sensor_dict(s: Sensor, node: Node | None = None) -> dict:
    return {
        "id": s.id, "building_id": s.building_id, "node_id": s.node_id, "node_name": node.name if node else None,
        "name": s.name, "type": s.type.value, "last_reading": s.last_reading, "triggered": s.triggered,
        "last_seen": s.last_seen.isoformat() if s.last_seen else None,
    }


@bp.get("/buildings/<int:building_id>/sensors")
@staff_required
def list_sensors(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    rows = SessionLocal.execute(select(Sensor, Node).join(Node, Sensor.node_id == Node.id).where(Sensor.building_id == b.id)).all()
    return {"items": [sensor_dict(s, n) for s, n in rows]}


@bp.post("/buildings/<int:building_id>/sensors")
@admin_required
@bp.input(SensorIn)
@bp.doc(summary="Register a sensor. The API key is shown only once")
def create_sensor(building_id: int, json_data: SensorIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    node = SessionLocal.get(Node, json_data.node_id)
    if node is None or node.building_id != b.id:
        abort(422, "Node is not in this building")
    key = new_token(24)
    s = Sensor(building_id=b.id, node_id=node.id, name=json_data.name, type=json_data.type, api_key_hash=hash_secret(key))
    SessionLocal.add(s)
    SessionLocal.commit()
    return {**sensor_dict(s, node), "api_key": key}, 201


@bp.post("/sensors/<int:sensor_id>/rotate-key")
@admin_required
def rotate_key(sensor_id: int):
    s = SessionLocal.get(Sensor, sensor_id)
    if s is None:
        abort(404)
    get_building_or_404(SessionLocal, s.building_id, current_user().society_id)
    key = new_token(24)
    s.api_key_hash = hash_secret(key)
    SessionLocal.commit()
    return {"id": s.id, "api_key": key}


@bp.delete("/sensors/<int:sensor_id>")
@admin_required
def delete_sensor(sensor_id: int):
    s = SessionLocal.get(Sensor, sensor_id)
    if s is None:
        abort(404)
    get_building_or_404(SessionLocal, s.building_id, current_user().society_id)
    SessionLocal.delete(s)
    SessionLocal.commit()
    return "", 204


@bp.post("/sensors/<int:sensor_id>/readings")
@bp.input(ReadingIn)
@bp.doc(summary="Sensor ingest (ESP32 etc.). Authenticate with header `X-Sensor-Key`", security=[])
def ingest(sensor_id: int, json_data: ReadingIn):
    s = SessionLocal.get(Sensor, sensor_id)
    key = request.headers.get("X-Sensor-Key", "")
    if s is None or not key or not secrets_match(key, s.api_key_hash):
        abort(401, "Unknown sensor or wrong key")
    return process_reading(SessionLocal, s, json_data.model_dump())


def process_reading(session: Session, sensor: Sensor, data: dict) -> dict:
    now = datetime.now(UTC)
    building = session.get(Building, sensor.building_id)
    settings = {**DEFAULT_BUILDING_SETTINGS, **(building.settings or {})}
    prev_rows = session.scalars(
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor.id, SensorReading.ts >= now - timedelta(minutes=3), SensorReading.temperature_c.is_not(None))
        .order_by(SensorReading.ts)
    ).all()
    previous = [(_aware(r.ts), r.temperature_c) for r in prev_rows]
    session.add(SensorReading(sensor_id=sensor.id, ts=now, **{k: data.get(k) for k in ("smoke", "temperature_c", "flame", "alarm")}))
    fire, reasons = evaluate({**data, "ts": now}, previous, settings)
    sensor.last_reading = {k: v for k, v in data.items() if v is not None}
    sensor.last_seen = now
    incident_created = None
    if fire and not sensor.triggered:
        sensor.triggered = True
        set_hazard(session, building, sensor.node_id, "fire", "sensor")
        inc, created = open_incident(session, building, "fire", {"source": "sensor", "sensor_id": sensor.id, "node_id": sensor.node_id, "reasons": reasons})
        log_event(session, building.id, inc.id, "sensor.triggered", {"sensor_id": sensor.id, "node_id": sensor.node_id, "reasons": reasons, "reading": sensor.last_reading})
        log_event(session, building.id, inc.id, "hazard.updated", {"node_id": sensor.node_id, "level": "fire", "source": "sensor"})
        incident_created = inc if created else None
    elif not fire and sensor.triggered:
        # sensors clearing do not auto-clear the hazard: a rescuer confirms in the dashboard
        sensor.triggered = False
    session.commit()
    if incident_created is not None:
        announce_incident(session, building, incident_created)
        session.commit()
    emit("sensor.reading", {"sensor_id": sensor.id, "node_id": sensor.node_id, "reading": sensor.last_reading, "triggered": sensor.triggered,
                            "reasons": reasons}, building_room(building.id))
    return {"ok": True, "fire": fire, "reasons": reasons}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@bp.get("/sensors/<int:sensor_id>/readings")
@staff_required
def readings(sensor_id: int):
    s = SessionLocal.get(Sensor, sensor_id)
    if s is None:
        abort(404)
    get_building_or_404(SessionLocal, s.building_id, current_user().society_id)
    limit = min(int(request.args.get("limit", 120)), 1000)
    rows = SessionLocal.scalars(select(SensorReading).where(SensorReading.sensor_id == s.id).order_by(SensorReading.ts.desc()).limit(limit)).all()
    return {"items": [{"ts": r.ts.isoformat(), "smoke": r.smoke, "temperature_c": r.temperature_c, "flame": r.flame, "alarm": r.alarm} for r in reversed(rows)]}


# ---------------------------------------------------------------------- hazards


@bp.get("/buildings/<int:building_id>/hazards")
@staff_required
def get_hazards(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    rows = SessionLocal.scalars(select(NodeHazard).where(NodeHazard.building_id == b.id)).all()
    return {"hazard_version": b.hazard_version,
            "items": [{"node_id": r.node_id, "level": r.level.value, "source": r.source, "updated_at": r.updated_at.isoformat()} for r in rows]}


@bp.post("/buildings/<int:building_id>/hazards")
@staff_required
@bp.input(HazardIn)
@bp.doc(summary="Rescuer marks / clears a hazard manually (overrides simulation, opens an incident for fire)")
def set_manual_hazard(building_id: int, json_data: HazardIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    node = SessionLocal.get(Node, json_data.node_id)
    if node is None or node.building_id != b.id:
        abort(422, "Node is not in this building")
    changed = set_hazard(SessionLocal, b, node.id, json_data.level.value, "manual")
    inc = None
    created = False
    if json_data.level == HazardLevel.FIRE:
        inc, created = open_incident(SessionLocal, b, "fire", {"source": "manual", "node_id": node.id, "by": current_user().id},
                                     is_simulation=b.mode.value == "simulation")
    from app.incidents.service import active_incident

    current = inc or active_incident(SessionLocal, b.id)
    log_event(SessionLocal, b.id, current.id if current else None, "hazard.updated",
              {"node_id": node.id, "level": json_data.level.value, "source": "manual", "by": current_user().id})
    SessionLocal.commit()
    if created:
        announce_incident(SessionLocal, b, inc)
        SessionLocal.commit()
    return {"changed": changed, "hazard_version": b.hazard_version}


@bp.delete("/buildings/<int:building_id>/hazards")
@staff_required
def clear_all_hazards(building_id: int):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    n = clear_hazards(SessionLocal, b)
    for s in SessionLocal.scalars(select(Sensor).where(Sensor.building_id == b.id)):
        s.triggered = False
    SessionLocal.commit()
    return {"cleared": n, "hazard_version": b.hazard_version}
