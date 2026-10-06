"""Per-building in-memory runtime held by the engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.engine.router import EvacRouter
from app.positioning import fingerprint as fp
from app.positioning.fallback import DeviceLocator, new_locator
from app.positioning.particle_filter import PFMap
from app.routing.graph import BuildingGraph
from app.simulation.world import Simulation


@dataclass
class DeviceInfo:
    device_id: str
    user_id: int
    name: str
    flat: str | None
    phone: str | None
    stairs_ok: bool
    building_id: int | None
    loaded_at: float = field(default_factory=time.time)


@dataclass
class SimControl:
    running: bool = False
    speed: float = 1.0
    phone_share: float = 0.1


class BuildingRuntime:
    def __init__(self, building_id: int, graph: BuildingGraph, settings: dict) -> None:
        self.building_id = building_id
        self.settings = settings
        self.graph = graph
        self.pf_map = PFMap(graph)
        self.router = EvacRouter(graph, settings)
        self.locators: dict[str, DeviceLocator] = {}
        self.fingerprint: fp.FingerprintModel | None = None
        self.fingerprint_samples = -1
        self.sim: Simulation | None = None
        self.sim_ctl = SimControl()
        self.sim_locators: dict[str, DeviceLocator] = {}
        self.statuses: dict[str, str] = {}  # device -> participant status
        self.last_fix: dict[str, dict] = {}
        self.last_route_version: dict[str, int] = {}
        self.last_signage: dict[int, dict] = {}
        self.last_snapshot_event = 0.0
        self.last_position_log: dict[str, float] = {}
        self.hazard_changed_at: float = time.time()
        self.hazard_version = -1
        self.incident_id: int | None = None
        self.incident_kind: str | None = None
        self.incident_started: float | None = None
        self.loc_errors: list[float] = []
        self.explicit: dict[int, tuple[str, str]] = {}
        self.name = ""
        self.mode = "live"
        self.footprint: list | None = None
        self.last_sim_summary = 0.0

    def rebuild(self, graph: BuildingGraph, settings: dict) -> None:
        """Graph edited: keep devices but reset geometry-dependent state."""
        self.graph = graph
        self.settings = settings
        self.pf_map = PFMap(graph)
        self.router = EvacRouter(graph, settings)
        self.locators.clear()
        self.sim_locators.clear()
        self.last_route_version.clear()
        if self.sim is not None:
            self.sim = None
            self.sim_ctl.running = False

    def locator(self, device_id: str) -> DeviceLocator:
        loc = self.locators.get(device_id)
        if loc is None:
            loc = new_locator(
                device_id, self.pf_map, int(self.settings.get("particles", 400)),
                floor_attenuation_db=float(self.settings.get("floor_attenuation_db", 15.0)),
            )
            self.locators[device_id] = loc
        return loc

    @property
    def incident_active(self) -> bool:
        return self.incident_id is not None
