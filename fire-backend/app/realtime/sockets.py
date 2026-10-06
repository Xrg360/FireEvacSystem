"""Socket.IO handlers (paper §VI: WebSockets + publish/subscribe).

Connect with ``auth = {"token": <JWT>}`` (app / dashboard) or ``{"signage_token": ...}`` (display).

Rooms joined automatically:
  * phone (token with device_id)  -> device:<id>, residents:<building>
  * staff (admin/rescuer)          -> building:<id> after emitting ``subscribe`` {building_id}
  * signage display                -> signage:<id>

Client -> server (phones): ``scan``, ``gps``, ``manual_location``, ``floor_confirm``
Server -> client: see ``contracts/events.schema.json``.
"""

from __future__ import annotations

import logging
import time
from functools import wraps

import jwt
from flask import request
from flask_socketio import ConnectionRefusedError, disconnect, join_room, leave_room
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.auth.security import STAFF_ROLES, decode_token
from app.db import SessionLocal
from app.extensions import socketio
from app.live.store import get_store
from app.models import Building, BuildingMode, Role, Signage, User, UserStatus
from app.realtime.emitter import building_room, device_room, now_ms, residents_room, signage_room

log = logging.getLogger(__name__)

# sid -> connection info
_conns: dict[str, dict] = {}


class _Reading(BaseModel):
    bssid: str = Field(pattern=r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
    rssi: float = Field(ge=-120, le=0)


class _Scan(BaseModel):
    readings: list[_Reading] = Field(max_length=200)


class _Gps(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0, le=5000)


def _db(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            SessionLocal.remove()

    return wrapper


@socketio.on("connect")
@_db
def on_connect(auth):
    auth = auth or {}
    sid = request.sid
    if auth.get("signage_token"):
        sign = SessionLocal.scalars(select(Signage).where(Signage.token == auth["signage_token"])).first()
        if sign is None:
            raise ConnectionRefusedError("unknown display")
        _conns[sid] = {"kind": "signage", "signage_id": sign.id, "building_id": sign.building_id}
        join_room(signage_room(sign.id))
        return True
    token = auth.get("token")
    if not token:
        raise ConnectionRefusedError("missing token")
    try:
        from flask import current_app

        claims = decode_token(token, current_app.config["FIRE"].jwt_secret)
    except jwt.PyJWTError as exc:
        raise ConnectionRefusedError("invalid token") from exc
    user = SessionLocal.get(User, int(claims["sub"]))
    if user is None or user.status != UserStatus.APPROVED:
        raise ConnectionRefusedError("account not approved")
    info = {"kind": "user", "user_id": user.id, "role": user.role.value, "society_id": user.society_id,
            "building_id": user.building_id, "device_id": claims.get("device_id")}
    _conns[sid] = info
    if info["device_id"]:
        join_room(device_room(info["device_id"]))
        if user.building_id:
            join_room(residents_room(user.building_id))
    return True


@socketio.on("disconnect")
def on_disconnect(*_args):
    _conns.pop(request.sid, None)


@socketio.on("subscribe")
@_db
def on_subscribe(data):
    info = _conns.get(request.sid)
    if not info or info.get("kind") != "user" or Role(info["role"]) not in STAFF_ROLES:
        return {"ok": False, "error": "forbidden"}
    b = SessionLocal.get(Building, int((data or {}).get("building_id", 0)))
    if b is None or b.society_id != info["society_id"]:
        return {"ok": False, "error": "not found"}
    for room in list(info.get("rooms", [])):
        leave_room(room)
    join_room(building_room(b.id))
    info["rooms"] = [building_room(b.id)]
    snap = get_store().get_snapshot(b.id)
    return {"ok": True, "snapshot": snap}


@socketio.on("unsubscribe")
def on_unsubscribe(_data=None):
    info = _conns.get(request.sid) or {}
    for room in info.get("rooms", []):
        leave_room(room)
    info["rooms"] = []
    return {"ok": True}


def _phone() -> dict | None:
    info = _conns.get(request.sid)
    if not info or not info.get("device_id") or not info.get("building_id"):
        return None
    return info


def _tracking_ok(building_id: int) -> bool:
    from app.incidents.service import active_incident

    b = SessionLocal.get(Building, building_id)
    return b is not None and (b.mode == BuildingMode.SIMULATION or active_incident(SessionLocal, b.id) is not None)


def _push(info: dict, kind: str, **data) -> dict:
    if not _tracking_ok(info["building_id"]):
        return {"ok": False, "tracking": False}
    get_store().push_inbox({"type": kind, "device_id": info["device_id"], "building_id": info["building_id"], "received": time.time(), **data})
    return {"ok": True, "ts": now_ms()}


@socketio.on("scan")
@_db
def on_scan(data):
    info = _phone()
    if info is None:
        return {"ok": False, "error": "not a phone session"}
    try:
        scan = _Scan.model_validate(data or {})
    except ValidationError as exc:
        return {"ok": False, "error": exc.errors()[0]["msg"]}
    return _push(info, "scan", readings=[r.model_dump() for r in scan.readings])


@socketio.on("gps")
@_db
def on_gps(data):
    info = _phone()
    if info is None:
        return {"ok": False}
    try:
        fix = _Gps.model_validate(data or {})
    except ValidationError as exc:
        return {"ok": False, "error": exc.errors()[0]["msg"]}
    return _push(info, "gps", **fix.model_dump())


@socketio.on("manual_location")
@_db
def on_manual(data):
    info = _phone()
    if info is None or not isinstance((data or {}).get("node_id"), int):
        return {"ok": False}
    return _push(info, "manual", node_id=data["node_id"])


@socketio.on("floor_confirm")
@_db
def on_floor_confirm(data):
    info = _phone()
    if info is None or not isinstance((data or {}).get("level"), int):
        return {"ok": False}
    return _push(info, "floor_confirm", level=data["level"])


@socketio.on("ping_server")
def on_ping(_data=None):
    return {"ts": now_ms()}


def force_disconnect(sid: str) -> None:  # pragma: no cover - admin tooling
    disconnect(sid)
