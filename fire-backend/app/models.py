"""Database models.

Hierarchy: Society -> Building (a block / tower) -> Floor -> Node/Edge graph.
Incidents, hazards, sensors, devices and the event log hang off a Building.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo; clients need the offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Role(enum.StrEnum):
    RESIDENT = "resident"
    SURVEYOR = "surveyor"
    RESCUER = "rescuer"
    SOCIETY_ADMIN = "society_admin"


class UserStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BuildingMode(enum.StrEnum):
    LIVE = "live"
    SIMULATION = "simulation"


class NodeType(enum.StrEnum):
    ROOM = "room"
    CORRIDOR = "corridor"
    STAIR = "stair"
    LIFT = "lift"
    EXIT = "exit"
    REFUGE = "refuge"
    ASSEMBLY = "assembly"


class EdgeKind(enum.StrEnum):
    DOOR = "door"
    CORRIDOR = "corridor"
    STAIR = "stair"
    LIFT = "lift"
    OUTDOOR = "outdoor"


class HazardLevel(enum.StrEnum):
    NONE = "none"
    RISK = "risk"
    SMOKE = "smoke"
    FIRE = "fire"


class IncidentStatus(enum.StrEnum):
    DETECTED = "detected"
    EVACUATING = "evacuating"
    ALL_CLEAR = "all_clear"
    CLOSED = "closed"


class ParticipantStatus(enum.StrEnum):
    UNKNOWN = "unknown"
    EVACUATING = "evacuating"
    SAFE = "safe"
    NEEDS_HELP = "needs_help"


class SensorType(enum.StrEnum):
    SMOKE = "smoke"
    TEMPERATURE = "temperature"
    FLAME = "flame"
    MULTI = "multi"
    ALARM_PANEL = "alarm_panel"


# --------------------------------------------------------------------------- society & users


class Society(Base):
    __tablename__ = "societies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(255))
    join_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    buildings: Mapped[list[Building]] = relationship(back_populates="society", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=32), default=Role.RESIDENT)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, length=16), default=UserStatus.PENDING
    )
    society_id: Mapped[int | None] = mapped_column(ForeignKey("societies.id", ondelete="CASCADE"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id", ondelete="SET NULL"))
    flat: Mapped[str | None] = mapped_column(String(32))
    home_node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="SET NULL"))
    # Residents who cannot use stairs are routed to refuge areas and flagged to rescuers.
    stairs_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    mobility_notes: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    devices: Mapped[list[Device]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    model: Mapped[str | None] = mapped_column(String(120))
    app_version: Mapped[str | None] = mapped_column(String(32))
    fcm_token: Mapped[str | None] = mapped_column(Text)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    user: Mapped[User] = relationship(back_populates="devices")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- building graph


DEFAULT_BUILDING_SETTINGS: dict = {
    # A* edge cost: length * (1 + alpha*hazard + beta*congestion + gamma*exit_load)
    "alpha": 4.0,
    "beta": 2.0,
    "gamma": 1.0,
    # occupancy / capacity ratio above which a node counts as congested
    "congestion_threshold": 0.8,
    # a congestion reroute must be at least this much cheaper than the current route
    "reroute_improvement": 0.15,
    # minimum seconds between two congestion reroutes for one person
    "reroute_cooldown_s": 10,
    # positioning
    "rssi_uncertainty_db": 6.0,
    "floor_attenuation_db": 15.0,
    "particles": 400,
    "low_confidence": 0.35,
    "floor_confirm_confidence": 0.6,
    # sensors
    "smoke_threshold": 300.0,
    "temp_threshold_c": 57.0,
    "rate_of_rise_c_per_min": 8.0,
}


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    society_id: Mapped[int] = mapped_column(ForeignKey("societies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[BuildingMode] = mapped_column(
        Enum(BuildingMode, native_enum=False, length=16), default=BuildingMode.LIVE
    )
    floor_height_m: Mapped[float] = mapped_column(Float, default=3.0)
    graph_version: Mapped[int] = mapped_column(Integer, default=1)
    hazard_version: Mapped[int] = mapped_column(Integer, default=1)
    # [[lat, lng], ...] polygon of the block's footprint, used by the GPS fallback.
    footprint: Mapped[list | None] = mapped_column(JSON)
    settings: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_BUILDING_SETTINGS))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    society: Mapped[Society] = relationship(back_populates="buildings")
    floors: Mapped[list[Floor]] = relationship(
        back_populates="building", cascade="all, delete-orphan", order_by="Floor.level"
    )

    def setting(self, key: str):
        return (self.settings or {}).get(key, DEFAULT_BUILDING_SETTINGS.get(key))


class Floor(Base):
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("building_id", "level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    width_m: Mapped[float] = mapped_column(Float, default=30.0)
    height_m: Mapped[float] = mapped_column(Float, default=20.0)
    plan_image: Mapped[str | None] = mapped_column(String(255))
    # pixels per metre of the uploaded plan image
    scale_px_per_m: Mapped[float | None] = mapped_column(Float)

    building: Mapped[Building] = relationship(back_populates="floors")


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("building_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[int] = mapped_column(ForeignKey("floors.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[NodeType] = mapped_column(Enum(NodeType, native_enum=False, length=16))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    # people the space holds comfortably (congestion denominator)
    capacity: Mapped[int] = mapped_column(Integer, default=10)
    # exits only: people per minute that can pass through
    exit_flow_per_min: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    a_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    b_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    kind: Mapped[EdgeKind] = mapped_column(Enum(EdgeKind, native_enum=False, length=16), default=EdgeKind.CORRIDOR)
    # walking length in metres; never shorter than the straight-line distance
    length_m: Mapped[float | None] = mapped_column(Float)
    width_m: Mapped[float] = mapped_column(Float, default=1.2)
    accessible: Mapped[bool] = mapped_column(Boolean, default=True)


class AccessPoint(Base):
    __tablename__ = "access_points"
    __table_args__ = (UniqueConstraint("building_id", "bssid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[int] = mapped_column(ForeignKey("floors.id", ondelete="CASCADE"))
    bssid: Mapped[str] = mapped_column(String(17))
    ssid: Mapped[str | None] = mapped_column(String(64))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    # eq. 1: received power at the reference distance (1 m) and path loss exponent
    p_ref: Mapped[float] = mapped_column(Float, default=-40.0)
    eta: Mapped[float] = mapped_column(Float, default=2.7)
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class FingerprintSample(Base):
    __tablename__ = "fingerprint_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(36))
    # {bssid: rssi_dbm}
    readings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Signage(Base):
    __tablename__ = "signage"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)


# --------------------------------------------------------------------------- sensors & hazards


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[SensorType] = mapped_column(Enum(SensorType, native_enum=False, length=16))
    api_key_hash: Mapped[str] = mapped_column(String(128))
    last_reading: Mapped[dict | None] = mapped_column(JSON)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime())
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_sensor_readings_sensor_ts", "sensor_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensors.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    smoke: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    flame: Mapped[bool | None] = mapped_column(Boolean)
    alarm: Mapped[bool | None] = mapped_column(Boolean)


class NodeHazard(Base):
    __tablename__ = "node_hazards"

    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    level: Mapped[HazardLevel] = mapped_column(Enum(HazardLevel, native_enum=False, length=16))
    # sensor | simulation | manual
    source: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


# --------------------------------------------------------------------------- incidents


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="fire")  # fire | drill
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False, length=16), default=IncidentStatus.DETECTED
    )
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    metrics: Mapped[dict | None] = mapped_column(JSON)


class IncidentParticipant(Base):
    __tablename__ = "incident_participants"
    __table_args__ = (UniqueConstraint("incident_id", "device_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[ParticipantStatus] = mapped_column(
        Enum(ParticipantStatus, native_enum=False, length=16), default=ParticipantStatus.UNKNOWN
    )
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    safe_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    assigned_exit_id: Mapped[int | None] = mapped_column(Integer)


class SosRequest(Base):
    __tablename__ = "sos_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    device_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), default="help")  # help | trapped | medical
    note: Mapped[str | None] = mapped_column(String(500))
    node_id: Mapped[int | None] = mapped_column(Integer)
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    level: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_by: Mapped[int | None] = mapped_column(Integer)


class Event(Base):
    """Append-only log. Powers post-incident replay and metrics."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_incident_ts", "incident_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)


class PositionLog(Base):
    __tablename__ = "position_logs"
    __table_args__ = (Index("ix_position_logs_device_ts", "device_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    device_id: Mapped[str] = mapped_column(String(36))
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    level: Mapped[int] = mapped_column(Integer)
    node_id: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
