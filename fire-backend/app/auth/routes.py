"""Accounts: society join code -> resident signup -> admin approval. JWT access + refresh tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.auth.security import (
    admin_required,
    create_access_token,
    current_user,
    hash_password,
    login_required,
    require_device,
    staff_required,
    verify_password,
)
from app.db import SessionLocal
from app.live.store import get_store
from app.models import Building, Device, Floor, Node, RefreshToken, Role, Society, User, UserStatus

bp = APIBlueprint("auth", __name__, tag="auth")


# ---------------------------------------------------------------------- schemas


class RegisterIn(BaseModel):
    join_code: str = Field(min_length=4, max_length=16)
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    building_id: int | None = None
    flat: str | None = Field(default=None, max_length=32)
    home_node_id: int | None = None
    stairs_ok: bool = True
    mobility_notes: str | None = Field(default=None, max_length=255)


class DeviceIn(BaseModel):
    platform: str = "android"
    model: str | None = None
    app_version: str | None = None
    device_id: str | None = Field(default=None, description="Reuse a device id issued earlier to this install")


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str
    device: DeviceIn | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class FcmIn(BaseModel):
    fcm_token: str = Field(min_length=10)


class UserPatch(BaseModel):
    role: Role | None = None
    building_id: int | None = None
    flat: str | None = None
    stairs_ok: bool | None = None
    mobility_notes: str | None = None


class StaffIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    phone: str | None = None
    role: Role = Role.RESCUER


# ---------------------------------------------------------------------- helpers


def user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "phone": u.phone,
        "role": u.role.value,
        "status": u.status.value,
        "society_id": u.society_id,
        "building_id": u.building_id,
        "flat": u.flat,
        "home_node_id": u.home_node_id,
        "stairs_ok": u.stairs_ok,
        "mobility_notes": u.mobility_notes,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _issue_tokens(user: User, device_id: str | None) -> dict:
    cfg = current_app.config["FIRE"]
    rt = RefreshToken(user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=cfg.jwt_refresh_days))
    SessionLocal.add(rt)
    SessionLocal.commit()
    return {
        "access_token": create_access_token(user, device_id),
        "refresh_token": f"{rt.id}.{device_id or ''}",
        "expires_in": cfg.jwt_access_minutes * 60,
        "token_type": "Bearer",
        "device_id": device_id,
        "user": user_dict(user),
    }


# ---------------------------------------------------------------------- public


@bp.get("/join/<code>")
@bp.doc(summary="Society info for the signup screen (buildings, floors, rooms)")
def join_info(code: str):
    society = SessionLocal.scalars(select(Society).where(Society.join_code == code.upper())).first()
    if society is None:
        abort(404, "Unknown join code")
    buildings = SessionLocal.scalars(select(Building).where(Building.society_id == society.id)).all()
    out = []
    for b in buildings:
        floors = SessionLocal.scalars(select(Floor).where(Floor.building_id == b.id).order_by(Floor.level)).all()
        rooms = SessionLocal.scalars(select(Node).where(Node.building_id == b.id, Node.type == "room")).all()
        out.append(
            {
                "id": b.id,
                "name": b.name,
                "floors": [
                    {"id": f.id, "level": f.level, "name": f.name,
                     "rooms": [{"id": r.id, "name": r.name} for r in rooms if r.floor_id == f.id]}
                    for f in floors
                ],
            }
        )
    return {"society": {"id": society.id, "name": society.name, "address": society.address}, "buildings": out}


@bp.post("/auth/register")
@bp.input(RegisterIn)
@bp.doc(summary="Resident signup with the society join code; account starts as pending")
def register(json_data: RegisterIn):
    society = SessionLocal.scalars(select(Society).where(Society.join_code == json_data.join_code.upper())).first()
    if society is None:
        abort(404, "Unknown join code")
    if SessionLocal.scalars(select(User).where(User.email == json_data.email.lower())).first():
        abort(409, "An account with this email already exists")
    if json_data.building_id is not None:
        b = SessionLocal.get(Building, json_data.building_id)
        if b is None or b.society_id != society.id:
            abort(422, "Building does not belong to this society")
    user = User(
        email=json_data.email.lower(),
        password_hash=hash_password(json_data.password),
        name=json_data.name.strip(),
        phone=json_data.phone,
        role=Role.RESIDENT,
        status=UserStatus.PENDING,
        society_id=society.id,
        building_id=json_data.building_id,
        flat=json_data.flat,
        home_node_id=json_data.home_node_id,
        stairs_ok=json_data.stairs_ok,
        mobility_notes=json_data.mobility_notes,
    )
    SessionLocal.add(user)
    SessionLocal.commit()
    return {"user": user_dict(user), "message": "Registered. A society admin must approve your account."}, 201


@bp.post("/auth/login")
@bp.input(LoginIn)
@bp.doc(summary="Login. Mobile apps pass `device` to register this install and get a device-bound token")
def login(json_data: LoginIn):
    user = SessionLocal.scalars(select(User).where(User.email == json_data.email.lower())).first()
    if user is None or not verify_password(json_data.password, user.password_hash):
        abort(401, "Wrong email or password")
    if user.status == UserStatus.REJECTED:
        abort(403, "This account was rejected by the society admin")
    device_id = None
    if json_data.device is not None:
        dev = SessionLocal.get(Device, json_data.device.device_id) if json_data.device.device_id else None
        if dev is None or dev.user_id != user.id:
            dev = Device(user_id=user.id)
            SessionLocal.add(dev)
        dev.platform = json_data.device.platform
        dev.model = json_data.device.model
        dev.app_version = json_data.device.app_version
        dev.last_seen = datetime.now(UTC)
        SessionLocal.flush()
        device_id = dev.id
    return _issue_tokens(user, device_id)


@bp.post("/auth/refresh")
@bp.input(RefreshIn)
def refresh(json_data: RefreshIn):
    token_id, _, device_id = json_data.refresh_token.partition(".")
    rt = SessionLocal.get(RefreshToken, token_id)
    expires = rt.expires_at if rt else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if rt is None or rt.revoked or expires < datetime.now(UTC):
        abort(401, "Refresh token invalid or expired")
    user = SessionLocal.get(User, rt.user_id)
    if user is None or user.status == UserStatus.REJECTED:
        abort(401, "User not allowed")
    rt.revoked = True  # rotate
    return _issue_tokens(user, device_id or None)


@bp.post("/auth/logout")
@bp.input(RefreshIn)
def logout(json_data: RefreshIn):
    rt = SessionLocal.get(RefreshToken, json_data.refresh_token.partition(".")[0])
    if rt is not None:
        rt.revoked = True
        SessionLocal.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- signed in


@bp.get("/auth/me")
@login_required(approved=False)
def me():
    u = current_user()
    society = SessionLocal.get(Society, u.society_id) if u.society_id else None
    building = SessionLocal.get(Building, u.building_id) if u.building_id else None
    return {
        "user": user_dict(u),
        "society": {"id": society.id, "name": society.name, "join_code": society.join_code if u.role != Role.RESIDENT else None} if society else None,
        "building": {"id": building.id, "name": building.name, "mode": building.mode.value} if building else None,
    }


@bp.post("/devices/fcm")
@login_required(approved=False)
@bp.input(FcmIn)
@bp.doc(summary="Register this install's Firebase Cloud Messaging token")
def register_fcm(json_data: FcmIn):
    device_id = require_device()
    dev = SessionLocal.get(Device, device_id)
    if dev is None or dev.user_id != current_user().id:
        abort(404, "Device not found")
    dev.fcm_token = json_data.fcm_token
    dev.last_seen = datetime.now(UTC)
    SessionLocal.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- admin


@bp.get("/residents")
@staff_required
@bp.doc(summary="Residents of the admin's society (filter with ?status=pending)")
def list_residents():
    from flask import request

    q = select(User).where(User.society_id == current_user().society_id).order_by(User.created_at.desc())
    status = request.args.get("status")
    if status:
        q = q.where(User.status == UserStatus(status))
    users = SessionLocal.scalars(q).all()
    devices = SessionLocal.scalars(select(Device).where(Device.user_id.in_([u.id for u in users]))).all() if users else []
    by_user: dict[int, list[dict]] = {}
    for d in devices:
        by_user.setdefault(d.user_id, []).append(
            {"id": d.id, "model": d.model, "app_version": d.app_version, "push": bool(d.fcm_token),
             "last_seen": d.last_seen.isoformat() if d.last_seen else None}
        )
    return {"items": [{**user_dict(u), "devices": by_user.get(u.id, [])} for u in users]}


def _society_user(user_id: int) -> User:
    u = SessionLocal.get(User, user_id)
    if u is None or u.society_id != current_user().society_id:
        abort(404, "User not found")
    return u


@bp.post("/residents/<int:user_id>/approve")
@admin_required
def approve(user_id: int):
    u = _society_user(user_id)
    u.status = UserStatus.APPROVED
    SessionLocal.commit()
    for d in u.devices:
        get_store().push_inbox({"type": "device_refresh", "device_id": d.id})
    return user_dict(u)


@bp.post("/residents/<int:user_id>/reject")
@admin_required
def reject(user_id: int):
    u = _society_user(user_id)
    if u.id == current_user().id:
        abort(422, "You cannot reject yourself")
    u.status = UserStatus.REJECTED
    SessionLocal.commit()
    return user_dict(u)


@bp.patch("/residents/<int:user_id>")
@admin_required
@bp.input(UserPatch)
def patch_user(user_id: int, json_data: UserPatch):
    u = _society_user(user_id)
    data = json_data.model_dump(exclude_unset=True)
    if "building_id" in data and data["building_id"] is not None:
        b = SessionLocal.get(Building, data["building_id"])
        if b is None or b.society_id != u.society_id:
            abort(422, "Unknown building")
    for k, v in data.items():
        setattr(u, k, v)
    SessionLocal.commit()
    for d in u.devices:
        get_store().push_inbox({"type": "device_refresh", "device_id": d.id})
    return user_dict(u)


@bp.post("/staff")
@admin_required
@bp.input(StaffIn)
@bp.doc(summary="Create a rescuer / admin / surveyor account (approved immediately)")
def create_staff(json_data: StaffIn):
    if SessionLocal.scalars(select(User).where(User.email == json_data.email.lower())).first():
        abort(409, "Email already in use")
    u = User(
        email=json_data.email.lower(), password_hash=hash_password(json_data.password), name=json_data.name, phone=json_data.phone,
        role=json_data.role, status=UserStatus.APPROVED, society_id=current_user().society_id,
    )
    SessionLocal.add(u)
    SessionLocal.commit()
    return user_dict(u), 201
