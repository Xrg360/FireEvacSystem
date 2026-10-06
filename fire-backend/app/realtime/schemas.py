"""Socket.IO event contracts (server -> client). Exported to contracts/events.schema.json and
checked against real engine output in tests, so the dashboard and app can rely on them."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Event(BaseModel):
    model_config = ConfigDict(extra="allow")
    ts: int


class Gps(BaseModel):
    lat: float
    lng: float
    accuracy_m: float


class PositionFix(_Event):
    """`position.fix` -> device room."""

    device_id: str
    source: Literal["wifi_pf", "manual", "gps", "last_known", "unknown"]
    x: float | None
    y: float | None
    level: int | None
    node_id: int | None
    confidence: float
    floor_confidence: float
    spread_m: float | None
    outside: bool
    near_assembly_node: int | None
    needs_picker: bool
    confirm_floor: bool
    gps: Gps | None


class RouteNode(BaseModel):
    id: int
    key: str
    name: str
    type: str
    x: float
    y: float
    level: int


class RouteStep(BaseModel):
    node_id: int
    kind: Literal["start", "go", "stairs", "exit", "refuge", "arrive"]
    text: str
    distance_m: float


class RouteGoal(BaseModel):
    id: int
    name: str
    type: str


class RouteAssigned(_Event):
    """`route.assigned` -> device room. reason: initial | hazard | congestion | deviation | current."""

    device_id: str
    incident_id: int | None
    version: int
    reason: str
    path: list[int]
    nodes: list[RouteNode]
    steps: list[RouteStep]
    goal: RouteGoal
    goal_type: Literal["exit", "refuge"]
    remaining_m: float
    latency_ms: float | None


class IncidentInfo(BaseModel):
    id: int
    building_id: int
    kind: Literal["fire", "drill"]
    status: Literal["detected", "evacuating", "all_clear", "closed"]
    is_simulation: bool
    trigger: dict | None
    started_at: str | None
    ended_at: str | None


class IncidentUpdated(_Event):
    """`incident.updated` -> building room and residents room."""

    incident: IncidentInfo
    building_id: int
    building_name: str


class Kpis(BaseModel):
    active_devices: int
    real_devices: int
    virtual_occupants: int
    avg_path_length_m: float
    avg_path_nodes: float
    congestion_rate: float
    fire_alerts: int
    evacuated: int
    unaccounted: int
    needs_help: int
    trapped: int
    in_refuge: int
    route_cache_hit_rate: float


class ExitInfo(BaseModel):
    node_id: int
    name: str
    assigned: int
    queue: int
    flow_per_min: float
    capacity: int
    hazard: str


class LiveDevice(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    kind: Literal["real", "virtual"]
    name: str
    x: float | None
    y: float | None
    level: int | None
    node_id: int | None
    source: str
    confidence: float
    status: str
    stairs_ok: bool
    route: list[int]
    goal: int | None
    goal_type: str | None
    remaining_m: float | None
    progress: float | None


class SnapshotIncident(BaseModel):
    id: int
    kind: str | None
    started_at: float | None


class Snapshot(_Event):
    """`snapshot` -> building room, ~1 Hz (paper Fig. 3 dashboard)."""

    building_id: int
    name: str
    mode: Literal["live", "simulation"]
    graph_version: int
    hazard_version: int
    incident: SnapshotIncident | None
    kpis: Kpis
    hazards: dict[str, Literal["risk", "smoke", "fire"]]
    occupancy: dict[str, int]
    congestion: dict[str, float]
    predicted_congestion: dict[str, float]
    exits: list[ExitInfo]
    devices: list[LiveDevice]
    unaccounted: list[dict]
    sos: list[dict]
    sim: dict | None
    reroutes: dict[str, int]


class SignageUpdate(_Event):
    """`signage.update` -> signage room."""

    signage_id: int
    name: str
    status: Literal["normal", "evacuate", "exit", "danger"]
    message: str
    arrow_deg: float | None
    incident: bool
    hazard_here: str
    exits: list[dict]


class HazardsUpdate(_Event):
    """`hazards` -> residents room, whenever hazards change (phone map + offline routing)."""

    building_id: int
    hazard_version: int
    hazards: dict[str, Literal["risk", "smoke", "fire"]]


EVENTS: dict[str, type[BaseModel]] = {
    "hazards": HazardsUpdate,
    "position.fix": PositionFix,
    "route.assigned": RouteAssigned,
    "incident.updated": IncidentUpdated,
    "snapshot": Snapshot,
    "signage.update": SignageUpdate,
}
