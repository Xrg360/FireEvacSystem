"""The evacuation engine: one loop that turns sensor, scan and simulation input into routes.

Per tick (default 1 s), for every building (paper §IV "System flow"):
  1. Data collection   - drain the inbox (Wi-Fi scans, GPS, manual picks, status, sim commands)
                         and sync hazards / incidents / graph edits from the database.
  2. Data processing   - particle-filter positions, occupancy, congestion (+ ML prediction).
  3. Path planning     - A* routes for everyone; hazard / congestion rerouting.
  4. Output            - route.assigned + position.fix to phones, snapshot to dashboards,
                         signage.update to displays, event log for post-incident replay.

Run standalone (Docker):  python -m app.engine
Or inside the API process for local development (ENGINE_INPROCESS=1).
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.buildings.service import load_graph
from app.config import Config
from app.congestion.density import congestion_rate, congestion_ratios, occupancy
from app.congestion.predict import CongestionPredictor
from app.db import session_scope
from app.engine.router import Assignment
from app.engine.runtime import BuildingRuntime, DeviceInfo
from app.incidents.service import (
    active_incident,
    announce_incident,
    building_resident_devices,
    log_event,
    open_incident,
)
from app.live.store import LiveStore
from app.models import (
    DEFAULT_BUILDING_SETTINGS,
    Building,
    BuildingMode,
    Device,
    FingerprintSample,
    IncidentParticipant,
    NodeHazard,
    PositionLog,
    Signage,
    SosRequest,
    User,
)
from app.positioning import fingerprint as fp
from app.realtime.emitter import building_room, device_room, emit, residents_room, signage_room
from app.routing.planner import Person, plan_route, remaining_path
from app.routing.steps import bearing_deg, build_steps
from app.sensors.hazards import effective_hazards, explicit_hazards, set_hazard
from app.simulation.rssi_synth import synth_scan
from app.simulation.world import Simulation

log = logging.getLogger(__name__)

SNAPSHOT_EVENT_EVERY_S = 2.0
POSITION_LOG_EVERY_S = 5.0
FINGERPRINT_CHECK_EVERY_S = 30.0
DEVICE_CACHE_S = 60.0
SIM_SUMMARY_EVERY_S = 10.0
FIX_FRESH_S = 90.0


class Engine:
    def __init__(self, cfg: Config, store: LiveStore, predictor: CongestionPredictor | None = None) -> None:
        self.cfg = cfg
        self.store = store
        self.predictor = predictor or CongestionPredictor.load(cfg.model_dir)
        self.runtimes: dict[int, BuildingRuntime] = {}
        self.devices: dict[str, DeviceInfo] = {}
        self._stop = threading.Event()
        self._last_retention = 0.0
        self._last_fp_check: dict[int, float] = {}
        self._signage: dict[int, list[Signage]] = {}
        self._residents: dict[int, list[dict]] = {}
        self._open_sos: dict[int, list[dict]] = {}
        self._last_tick = time.time()

    # ------------------------------------------------------------------ loop

    def run_forever(self) -> None:
        log.info("engine started (tick %.2fs)", self.cfg.engine_tick_seconds)
        while not self._stop.is_set():
            started = time.time()
            try:
                self.tick()
            except Exception:
                log.exception("engine tick failed")
            elapsed = time.time() - started
            self._stop.wait(max(0.05, self.cfg.engine_tick_seconds - elapsed))

    def stop(self) -> None:
        self._stop.set()

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="fire-engine", daemon=True)
        t.start()
        return t

    def tick(self, now: float | None = None) -> None:
        now = now or time.time()
        dt = min(max(now - self._last_tick, 0.0), 5.0)
        self._last_tick = now
        with session_scope() as s:
            self._sync(s, now)
            for msg in self.store.drain_inbox():
                try:
                    self._handle(s, msg, now)
                except Exception:
                    log.exception("bad inbox message %s", msg.get("type"))
            for rt in list(self.runtimes.values()):
                self._step_building(s, rt, now, dt)
            if now - self._last_retention > 3600:
                self._retention(s)
                self._last_retention = now

    # ------------------------------------------------------------------ sync with database

    def _sync(self, s: Session, now: float) -> None:
        buildings = s.scalars(select(Building)).all()
        seen = set()
        for b in buildings:
            seen.add(b.id)
            settings = {**DEFAULT_BUILDING_SETTINGS, **(b.settings or {})}
            rt = self.runtimes.get(b.id)
            if rt is None or rt.graph.graph_version != b.graph_version:
                graph = load_graph(s, b)
                if rt is None:
                    rt = BuildingRuntime(b.id, graph, settings)
                    self.runtimes[b.id] = rt
                else:
                    rt.rebuild(graph, settings)
                self._signage[b.id] = s.scalars(select(Signage).where(Signage.building_id == b.id)).all()
                rt.hazard_version = -1
            rt.settings = settings
            rt.router.settings = settings
            rt.router.ctx.alpha, rt.router.ctx.beta, rt.router.ctx.gamma = (
                float(settings["alpha"]), float(settings["beta"]), float(settings["gamma"])
            )
            rt.name = b.name
            rt.mode = b.mode
            rt.footprint = b.footprint

            if rt.hazard_version != b.hazard_version:
                rows = s.scalars(select(NodeHazard).where(NodeHazard.building_id == b.id)).all()
                rt.explicit = {r.node_id: (r.level.value, r.source) for r in rows if r.level.value != "none"}
                latest = max((r.updated_at for r in rows), default=None)
                rt.hazard_changed_at = _epoch(latest) if latest else now
                rt.hazard_version = b.hazard_version

            inc = active_incident(s, b.id)
            if inc is not None and rt.incident_id != inc.id:
                rt.incident_id, rt.incident_kind = inc.id, inc.kind
                rt.incident_started = _epoch(inc.started_at)
                rt.statuses = {
                    p.device_id: p.status.value
                    for p in s.scalars(select(IncidentParticipant).where(IncidentParticipant.incident_id == inc.id))
                }
                self._residents[b.id] = self._load_residents(s, b.id)
                if rt.sim is not None and rt.sim.alarm_t is None:
                    rt.sim.start_alarm()
            elif inc is None and rt.incident_id is not None:
                self._incident_ended(s, rt)
            if inc is not None:
                self._open_sos[b.id] = self._load_sos(s, b.id, inc.id)

            if now - self._last_fp_check.get(b.id, 0.0) > FINGERPRINT_CHECK_EVERY_S:
                self._last_fp_check[b.id] = now
                self._refresh_fingerprint(s, rt)
        for bid in list(self.runtimes):
            if bid not in seen:
                del self.runtimes[bid]

    def _refresh_fingerprint(self, s: Session, rt: BuildingRuntime, force: bool = False) -> None:
        count = s.scalar(select(func.count(FingerprintSample.id)).where(FingerprintSample.building_id == rt.building_id)) or 0
        if not force and count == rt.fingerprint_samples:
            return
        rows = s.scalars(select(FingerprintSample).where(FingerprintSample.building_id == rt.building_id)).all()
        samples = [(r.node_id, r.readings) for r in rows if r.node_id in rt.graph.nodes]
        rt.fingerprint = fp.train(samples)
        rt.fingerprint_samples = count

    def _load_residents(self, s: Session, building_id: int) -> list[dict]:
        return [
            {"device_id": d.id, "user_id": u.id, "name": u.name, "flat": u.flat, "phone": u.phone, "stairs_ok": u.stairs_ok}
            for d, u in building_resident_devices(s, building_id)
        ]

    def _load_sos(self, s: Session, building_id: int, incident_id: int) -> list[dict]:
        from app.incidents.service import sos_dict

        rows = s.execute(
            select(SosRequest, User)
            .outerjoin(User, SosRequest.user_id == User.id)
            .where(SosRequest.building_id == building_id, SosRequest.incident_id == incident_id, SosRequest.resolved_at.is_(None))
        ).all()
        return [sos_dict(r, u) for r, u in rows]

    def _device(self, s: Session, device_id: str) -> DeviceInfo | None:
        info = self.devices.get(device_id)
        if info is not None and time.time() - info.loaded_at < DEVICE_CACHE_S:
            return info
        row = s.execute(select(Device, User).join(User, Device.user_id == User.id).where(Device.id == device_id)).first()
        if row is None:
            return None
        d, u = row
        info = DeviceInfo(d.id, u.id, u.name, u.flat, u.phone, u.stairs_ok, u.building_id)
        self.devices[device_id] = info
        return info

    # ------------------------------------------------------------------ inbox

    def _tracking_allowed(self, rt: BuildingRuntime) -> bool:
        """Privacy: positions are only processed during an incident/drill, or in simulation mode."""
        return rt.incident_active or rt.mode == BuildingMode.SIMULATION

    def _handle(self, s: Session, msg: dict, now: float) -> None:
        kind = msg.get("type")
        if kind == "sim":
            self._sim_command(s, msg, now)
            return
        if kind == "retrain":
            rt = self.runtimes.get(msg["building_id"])
            if rt:
                self._refresh_fingerprint(s, rt, force=True)
            return
        if kind == "device_refresh":
            self.devices.pop(msg.get("device_id"), None)
            return
        device_id = msg.get("device_id")
        rt = self.runtimes.get(msg.get("building_id"))
        if not device_id or rt is None:
            return
        if kind == "status":
            rt.statuses[device_id] = msg["status"]
            if msg["status"] == "safe":
                rt.router.release(device_id)
            return
        if not self._tracking_allowed(rt):
            return
        loc = rt.locator(device_id)
        if kind == "scan":
            readings = {r["bssid"].lower(): float(r["rssi"]) for r in msg.get("readings", []) if r.get("bssid")}
            loc.on_scan(readings, now, rt.fingerprint, float(rt.settings["rssi_uncertainty_db"]))
        elif kind == "gps":
            loc.on_gps(float(msg["lat"]), float(msg["lng"]), float(msg.get("accuracy_m", 50)), now)
        elif kind == "manual":
            if msg.get("node_id") in rt.graph.nodes:
                loc.on_manual(int(msg["node_id"]), now)
        elif kind == "floor_confirm":
            loc.on_floor_confirm(int(msg["level"]), now)

    # ------------------------------------------------------------------ simulation control

    def _sim_command(self, s: Session, msg: dict, now: float) -> None:
        rt = self.runtimes.get(msg["building_id"])
        if rt is None:
            return
        action = msg.get("action")
        b = s.get(Building, rt.building_id)
        if action in {"start", "reset"} or (rt.sim is None and action in {"spawn", "ignite"}):
            if rt.sim is not None:
                for oid in list(rt.sim.occupants):
                    rt.router.release(oid)
            rt.sim = Simulation(
                rt.graph, rt.router, rng=np.random.default_rng(msg.get("seed")),
                fire_spread_per_min=float(msg.get("spread_per_min", 0.6)), predictor=self.predictor,
                fire_rng=np.random.default_rng(None if msg.get("seed") is None else msg["seed"] + 1),
            )
            rt.sim_locators.clear()
            rt.loc_errors.clear()
            if action == "reset" and b is not None:
                from app.sensors.hazards import clear_hazards

                clear_hazards(s, b, source="simulation")
            rt.sim_ctl.running = action != "reset"
        sim = rt.sim
        if sim is None:
            return
        if action == "start":
            sim.spawn(int(msg.get("occupants", 0)), float(msg.get("phone_share", 0.1)), float(msg.get("mobility_share", 0.05)))
            if rt.incident_active:
                sim.start_alarm()
        elif action == "spawn":
            sim.spawn(int(msg.get("occupants", 10)), float(msg.get("phone_share", 0.1)), float(msg.get("mobility_share", 0.05)))
            if sim.alarm_t is not None:
                sim.start_alarm()
        elif action == "ignite":
            sim.fire.ignite(int(msg["node_id"]), sim.t)
            rt.sim_ctl.running = True
        elif action == "extinguish":
            sim.fire.extinguish(int(msg["node_id"]))
            if b is not None:
                set_hazard(s, b, int(msg["node_id"]), "none", "simulation")
        elif action == "pause":
            rt.sim_ctl.running = False
        elif action == "resume":
            rt.sim_ctl.running = True
        elif action == "speed":
            rt.sim_ctl.speed = float(np.clip(float(msg.get("speed", 1.0)), 0.25, 10.0))
        elif action == "spread":
            sim.fire.rate = float(msg.get("spread_per_min", 0.6)) / 60.0
        elif action == "alarm":
            sim.start_alarm()
        elif action == "stop":
            self._log_sim_summary(s, rt)
            for oid in list(sim.occupants):
                rt.router.release(oid)
            rt.sim = None
            rt.sim_ctl.running = False
            if b is not None:
                from app.sensors.hazards import clear_hazards

                clear_hazards(s, b, source="simulation")

    # ------------------------------------------------------------------ per building step

    def _step_building(self, s: Session, rt: BuildingRuntime, now: float, dt: float) -> None:
        b = s.get(Building, rt.building_id)
        if b is None:
            return
        explicit = getattr(rt, "explicit", {})

        # ---- simulation advances first so its fire becomes a hazard this tick
        sim_running = rt.sim is not None and rt.sim_ctl.running and rt.mode == BuildingMode.SIMULATION
        fixes = {dev: loc.fix(now, rt.footprint, rt.settings) for dev, loc in rt.locators.items()}
        real_nodes = {
            dev: fx["node_id"]
            for dev, fx in fixes.items()
            if fx["node_id"] is not None and not fx["outside"] and rt.statuses.get(dev) != "safe" and fx["source"] != "unknown"
        }
        if sim_running:
            sim = rt.sim
            sim.extra_hazards = {n: lvl for n, (lvl, src) in explicit.items() if src != "simulation"}
            sim.external_nodes = real_nodes
            if rt.incident_active and sim.alarm_t is None:
                sim.start_alarm()
            remaining = dt * rt.sim_ctl.speed
            while remaining > 1e-6:
                step = min(0.5, remaining)
                sim.step(step)
                remaining -= step
            self._sim_phones(rt, sim)
            # mirror simulated fire into the hazard table (dashboards, phones and replay see it)
            sim_fire = set(sim.fire.fire)
            db_sim_fire = {n for n, (lvl, src) in explicit.items() if src == "simulation" and lvl == "fire"}
            changed = False
            for n in sim_fire - db_sim_fire:
                changed |= set_hazard(s, b, n, "fire", "simulation")
            for n in db_sim_fire - sim_fire:
                changed |= set_hazard(s, b, n, "none", "simulation")
            if changed:
                s.flush()
                rt.explicit = explicit_hazards(s, b.id)
                explicit = rt.explicit
                rt.hazard_version = b.hazard_version
                rt.hazard_changed_at = now
                log_event(s, b.id, rt.incident_id, "hazard.updated", {"hazards": {str(k): v[0] for k, v in explicit.items()}, "source": "simulation"})
            if sim_fire and not rt.incident_active:
                inc, created = open_incident(s, b, "fire", {"source": "simulation", "nodes": sorted(sim_fire)}, is_simulation=True)
                if created:
                    s.flush()
                    announce_incident(s, b, inc)
                    rt.incident_id, rt.incident_kind, rt.incident_started = inc.id, inc.kind, now
                    rt.statuses = {}
                    self._residents[b.id] = self._load_residents(s, b.id)
                    sim.start_alarm()

        hazards = effective_hazards(rt.graph, {n: lvl for n, (lvl, _src) in explicit.items()})
        if getattr(rt, "hazards_sent_version", None) != rt.hazard_version:
            # residents' phones keep the latest hazards for their map and for offline routing
            rt.hazards_sent_version = rt.hazard_version
            emit("hazards", {"building_id": rt.building_id, "hazard_version": rt.hazard_version,
                             "hazards": {str(k): v for k, v in hazards.items()}}, residents_room(rt.building_id))

        # ---- occupancy / congestion context (the simulator already did this when running)
        if not sim_running:
            occ = occupancy(real_nodes.values())
            ratios = congestion_ratios(rt.graph, occ)
            predicted = None
            if rt.incident_active and real_nodes:
                predicted = self.predictor.predict(
                    rt.graph, occ, rt.router.remaining_routes(real_nodes), now - (rt.incident_started or now)
                )
            rt.router.update_context(hazards, ratios, predicted, rt.hazard_version, incident_active=rt.incident_active)

        # ---- route real phones
        for dev, fx in fixes.items():
            info = self._device(s, dev)
            if not rt.incident_active or rt.statuses.get(dev) == "safe" or fx["outside"]:
                if dev in rt.router.assignments:
                    rt.router.release(dev)
                    emit("route.cleared", {"device_id": dev, "reason": "outside" if fx["outside"] else "inactive"}, device_room(dev))
                continue
            node = fx["node_id"]
            if node is None:
                continue
            decision = rt.router.route(dev, node, now, Person(info.stairs_ok if info else True))
            if decision.changed:
                self._emit_route(s, rt, dev, node, decision.assignment, decision.reason, now)

        # ---- position fixes back to each phone
        for dev, fx in fixes.items():
            prev = rt.last_fix.get(dev)
            if prev is None or _fix_changed(prev, fx):
                rt.last_fix[dev] = fx
                emit("position.fix", {"device_id": dev, **fx}, device_room(dev))
            a = rt.router.assignments.get(dev)
            self.store.set_device(dev, {"fix": fx, "route": self._route_payload(rt, dev, fx["node_id"], a, "current", None) if a else None,
                                        "incident": rt.incident_id, "building_id": rt.building_id})
            if rt.incident_active and fx["x"] is not None and now - rt.last_position_log.get(dev, 0) >= POSITION_LOG_EVERY_S:
                rt.last_position_log[dev] = now
                s.add(PositionLog(building_id=rt.building_id, incident_id=rt.incident_id, device_id=dev, x=fx["x"], y=fx["y"],
                                  level=fx["level"], node_id=fx["node_id"], source=fx["source"], confidence=fx["confidence"]))

        # ---- dashboards
        snapshot = self._snapshot(s, rt, fixes, hazards, now)
        self.store.set_snapshot(rt.building_id, snapshot)
        emit("snapshot", snapshot, building_room(rt.building_id))
        if rt.incident_active and now - rt.last_snapshot_event >= SNAPSHOT_EVENT_EVERY_S:
            rt.last_snapshot_event = now
            log_event(s, rt.building_id, rt.incident_id, "snapshot", _compact_snapshot(snapshot))
        if rt.sim is not None and rt.incident_active and now - getattr(rt, "last_sim_summary", 0) >= SIM_SUMMARY_EVERY_S:
            rt.last_sim_summary = now
            self._log_sim_summary(s, rt)

        # ---- digital signage
        self._update_signage(rt, hazards)

    # ------------------------------------------------------------------ helpers: routes

    def _remaining_length(self, rt: BuildingRuntime, path: list[int]) -> float:
        return sum(rt.graph.walk_length(a, b) for a, b in zip(path, path[1:], strict=False))

    def _route_payload(self, rt: BuildingRuntime, dev: str, node: int | None, a: Assignment, reason: str, latency_ms: float | None) -> dict:
        path = remaining_path(a.path, node) if node is not None else a.path
        path = path or a.path
        g = rt.graph
        goal = g.nodes[a.goal]
        return {
            "device_id": dev,
            "incident_id": rt.incident_id,
            "version": a.version,
            "reason": reason,
            "path": path,
            "nodes": [{"id": n, "key": g.nodes[n].key, "name": g.nodes[n].name, "type": g.nodes[n].type,
                       "x": g.nodes[n].x, "y": g.nodes[n].y, "level": g.nodes[n].level} for n in path],
            "steps": build_steps(g, path),
            "goal": {"id": goal.id, "name": goal.name, "type": goal.type},
            "goal_type": a.goal_type,
            "remaining_m": round(self._remaining_length(rt, path), 1),
            "latency_ms": latency_ms,
        }

    def _emit_route(self, s: Session, rt: BuildingRuntime, dev: str, node: int, a: Assignment | None, reason: str, now: float) -> None:
        if a is None:
            emit("route.none", {"device_id": dev, "incident_id": rt.incident_id, "message": "No safe route found. Stay low, close doors, use SOS."}, device_room(dev))
            log_event(s, rt.building_id, rt.incident_id, "route.none", {"device_id": dev, "node_id": node})
            return
        latency_ms = round((now - rt.hazard_changed_at) * 1000.0, 1) if reason == "hazard" else None
        payload = self._route_payload(rt, dev, node, a, reason, latency_ms)
        emit("route.assigned", payload, device_room(dev))
        log_event(s, rt.building_id, rt.incident_id, "route.assigned",
                  {"device_id": dev, "reason": reason, "version": a.version, "path": payload["path"], "goal": a.goal,
                   "remaining_m": payload["remaining_m"], "latency_ms": latency_ms})
        if rt.incident_id:
            p = s.scalars(select(IncidentParticipant).where(IncidentParticipant.incident_id == rt.incident_id,
                                                            IncidentParticipant.device_id == dev)).first()
            if p is not None:
                p.assigned_exit_id = a.goal

    # ------------------------------------------------------------------ helpers: simulation phones

    def _sim_phones(self, rt: BuildingRuntime, sim: Simulation) -> None:
        """Virtual phones send synthetic scans through the real positioning pipeline."""
        from app.positioning.fallback import new_locator

        for o in sim.occupants.values():
            if not o.is_phone or not o.active or sim.t - o.last_scan < 3.0:
                continue
            o.last_scan = sim.t
            x, y, level = o.position(rt.graph)
            loc = rt.sim_locators.get(o.id)
            if loc is None:
                loc = new_locator(o.id, rt.pf_map, 200, floor_attenuation_db=float(rt.settings.get("floor_attenuation_db", 15.0)))
                rt.sim_locators[o.id] = loc
            est = loc.on_scan(synth_scan(rt.graph, x, y, level, sim.rng), sim.t, rt.fingerprint, float(rt.settings["rssi_uncertainty_db"]))
            if est is not None:
                err = float(np.hypot(est.x - x, est.y - y) + rt.graph.floor_height * abs(est.level - level))
                rt.loc_errors.append(err)
                if len(rt.loc_errors) > 2000:
                    rt.loc_errors = rt.loc_errors[-2000:]

    def _log_sim_summary(self, s: Session, rt: BuildingRuntime) -> None:
        if rt.sim is None:
            return
        summary = rt.sim.summary()
        if rt.loc_errors:
            summary["localization_median_error_m"] = round(float(np.median(rt.loc_errors)), 2)
            summary["localization_p90_error_m"] = round(float(np.percentile(rt.loc_errors, 90)), 2)
        log_event(s, rt.building_id, rt.incident_id, "sim.summary", summary)

    def _incident_ended(self, s: Session, rt: BuildingRuntime) -> None:
        for pid in list(rt.router.assignments):
            if not pid.startswith("sim-"):
                rt.router.release(pid)
                emit("route.cleared", {"device_id": pid, "reason": "incident_closed"}, device_room(pid))
        rt.incident_id = None
        rt.incident_kind = None
        rt.incident_started = None
        rt.statuses = {}
        rt.last_route_version.clear()
        if rt.mode != BuildingMode.SIMULATION:
            # privacy: positions are only kept while an incident/drill is open
            for dev in list(rt.locators):
                self.store.set_device(dev, {"fix": None, "route": None, "incident": None, "building_id": rt.building_id})
            rt.locators.clear()
            rt.last_fix.clear()
            rt.last_position_log.clear()
        if rt.sim is not None:
            rt.sim.alarm_t = None

    # ------------------------------------------------------------------ dashboard snapshot (paper Fig. 3)

    def _snapshot(self, s: Session, rt: BuildingRuntime, fixes: dict[str, dict], hazards: dict[int, str], now: float) -> dict:
        g = rt.graph
        devices = []
        path_lengths: list[float] = []
        path_nodes: list[int] = []
        residents = {r["device_id"]: r for r in self._residents.get(rt.building_id, [])}
        for dev, fx in fixes.items():
            if fx["source"] == "unknown" and dev not in residents:
                continue
            info = self.devices.get(dev)
            a = rt.router.assignments.get(dev)
            rem = remaining_path(a.path, fx["node_id"]) if a and fx["node_id"] is not None else []
            rem_len = self._remaining_length(rt, rem) if rem else None
            if rem:
                path_lengths.append(rem_len)
                path_nodes.append(len(rem))
            devices.append({
                "id": dev, "kind": "real", "name": info.name if info else dev[:8], "flat": info.flat if info else None,
                "phone": info.phone if info else None, "stairs_ok": info.stairs_ok if info else True,
                "x": fx["x"], "y": fx["y"], "level": fx["level"], "node_id": fx["node_id"], "source": fx["source"],
                "confidence": fx["confidence"], "spread_m": fx["spread_m"], "outside": fx["outside"],
                "needs_picker": fx["needs_picker"], "status": rt.statuses.get(dev, "unknown"),
                "route": rem, "goal": a.goal if a else None, "goal_type": a.goal_type if a else None,
                "remaining_m": None if rem_len is None else round(rem_len, 1),
                "progress": _progress(a, rem_len), "gps": fx["gps"],
            })
        sim = rt.sim
        sim_payload = None
        trapped = in_refuge = sim_safe = 0
        if sim is not None:
            for o in sim.occupants.values():
                if o.state in {"safe"}:
                    sim_safe += 1
                    continue
                if o.state == "trapped":
                    trapped += 1
                if o.state == "refuge":
                    in_refuge += 1
                x, y, level = o.position(g)
                a = rt.router.assignments.get(o.id)
                rem = remaining_path(a.path, o.node) if a else []
                rem_len = self._remaining_length(rt, rem) if rem else None
                if rem and o.active:
                    path_lengths.append(rem_len)
                    path_nodes.append(len(rem))
                devices.append({
                    "id": o.id, "kind": "virtual", "name": o.id, "x": round(x, 2), "y": round(y, 2), "level": level,
                    "node_id": o.location_node(), "source": "simulated", "confidence": 1.0, "status": o.state,
                    "stairs_ok": o.stairs_ok, "route": rem, "goal": a.goal if a else None, "goal_type": a.goal_type if a else None,
                    "remaining_m": None if rem_len is None else round(rem_len, 1), "progress": _progress(a, rem_len),
                    "is_phone": o.is_phone,
                })
            sim_payload = {
                "running": rt.sim_ctl.running, "speed": rt.sim_ctl.speed, "t": round(sim.t, 1),
                "alarm_t": sim.alarm_t, "summary": sim.summary(),
                "localization_median_error_m": round(float(np.median(rt.loc_errors)), 2) if rt.loc_errors else None,
            }

        occ_nodes = [d["node_id"] for d in devices if d["status"] not in {"safe", "trapped"} and d.get("node_id") is not None]
        occ = occupancy(occ_nodes)
        ratios = congestion_ratios(g, occ)
        threshold = float(rt.settings["congestion_threshold"])
        exits = []
        for e in g.exits:
            node = g.nodes[e]
            exits.append({
                "node_id": e, "name": node.name, "assigned": rt.router.ctx.exit_assigned.get(e, 0),
                "queue": occ.get(e, 0),
                "flow_per_min": node.exit_flow_per_min or 40.0, "capacity": node.capacity,
                "hazard": hazards.get(e, "none"),
            })
        real_status = [rt.statuses.get(r, "unknown") for r in residents]
        unaccounted = [
            {**r, "status": rt.statuses.get(dev, "unknown"), "last_fix": rt.last_fix.get(dev)}
            for dev, r in residents.items() if rt.statuses.get(dev, "unknown") in {"unknown", "evacuating", "needs_help"}
        ] if rt.incident_active else []
        active = [d for d in devices if d["status"] not in {"safe", "trapped", "refuge"}]
        return {
            "building_id": rt.building_id,
            "name": getattr(rt, "name", ""),
            "mode": rt.mode.value if hasattr(rt.mode, "value") else rt.mode,
            "graph_version": g.graph_version,
            "hazard_version": rt.hazard_version,
            "incident": {"id": rt.incident_id, "kind": rt.incident_kind, "started_at": rt.incident_started} if rt.incident_active else None,
            "kpis": {
                "active_devices": len(active),
                "real_devices": sum(1 for d in devices if d["kind"] == "real"),
                "virtual_occupants": sum(1 for d in devices if d["kind"] == "virtual"),
                "avg_path_length_m": round(statistics.mean(path_lengths), 1) if path_lengths else 0.0,
                "avg_path_nodes": round(statistics.mean(path_nodes), 2) if path_nodes else 0.0,
                "congestion_rate": round(congestion_rate(g, ratios, threshold), 3),
                "fire_alerts": sum(1 for v in hazards.values() if v == "fire"),
                "evacuated": sum(1 for v in real_status if v == "safe") + sim_safe,
                "unaccounted": len(unaccounted),
                "needs_help": sum(1 for v in real_status if v == "needs_help") + len(self._open_sos.get(rt.building_id, [])),
                "trapped": trapped,
                "in_refuge": in_refuge,
                "route_cache_hit_rate": round(rt.router.cache.hits / max(1, rt.router.cache.hits + rt.router.cache.misses), 3),
            },
            "hazards": {str(k): v for k, v in hazards.items()},
            "occupancy": {str(k): v for k, v in occ.items()},
            "congestion": {str(k): round(v, 2) for k, v in ratios.items()},
            "predicted_congestion": {str(k): round(v, 2) for k, v in rt.router.ctx.predicted_congestion.items() if v >= 0.25},
            "exits": exits,
            "devices": devices,
            "unaccounted": unaccounted,
            "sos": self._open_sos.get(rt.building_id, []) if rt.incident_active else [],
            "sim": sim_payload,
            "reroutes": dict(rt.router.reroute_count),
        }

    # ------------------------------------------------------------------ digital signage (paper §III-E)

    def _update_signage(self, rt: BuildingRuntime, hazards: dict[int, str]) -> None:
        for sign in self._signage.get(rt.building_id, []):
            if sign.node_id not in rt.graph.nodes:
                continue
            plan = plan_route(rt.graph, sign.node_id, rt.router.ctx, Person())
            if plan is None:
                state = {"status": "danger", "message": "No safe exit from here. Follow rescuers' instructions.", "arrow_deg": None}
            elif len(plan.path) == 1:
                state = {"status": "exit", "message": f"Exit here: {rt.graph.nodes[plan.goal].name}", "arrow_deg": None,
                         "exit": rt.graph.nodes[plan.goal].name}
            else:
                nxt = plan.path[1]
                nxt_node = rt.graph.nodes[nxt]
                vertical = None
                if nxt_node.level != rt.graph.nodes[sign.node_id].level:
                    vertical = "down" if nxt_node.level < rt.graph.nodes[sign.node_id].level else "up"
                state = {
                    "status": "evacuate" if rt.incident_active else "normal",
                    "arrow_deg": round(bearing_deg(rt.graph, sign.node_id, nxt)),
                    "vertical": vertical,
                    "next": nxt_node.name,
                    "exit": rt.graph.nodes[plan.goal].name,
                    "distance_m": round(plan.length, 0),
                    "message": f"Exit: {rt.graph.nodes[plan.goal].name} via {nxt_node.name}",
                }
            state["hazard_here"] = hazards.get(sign.node_id, "none")
            state["incident"] = rt.incident_active
            state["exits"] = [
                {"name": rt.graph.nodes[e].name, "hazard": hazards.get(e, "none"), "assigned": rt.router.ctx.exit_assigned.get(e, 0)}
                for e in rt.graph.exits
            ]
            if rt.last_signage.get(sign.id) != state:
                rt.last_signage[sign.id] = state
                emit("signage.update", {"signage_id": sign.id, "name": sign.name, **state}, signage_room(sign.id))
                self.store.set_json(f"signage:{sign.id}", {"signage_id": sign.id, "name": sign.name, **state})

    # ------------------------------------------------------------------ privacy retention

    def _retention(self, s: Session) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=self.cfg.position_retention_days)
        res = s.execute(delete(PositionLog).where(PositionLog.ts < cutoff))
        if res.rowcount:
            log.info("retention: deleted %d position rows older than %s", res.rowcount, cutoff.date())


def _epoch(dt: datetime | None) -> float:
    if dt is None:
        return time.time()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _fix_changed(a: dict, b: dict) -> bool:
    keys = ("source", "level", "node_id", "needs_picker", "confirm_floor", "outside", "near_assembly_node")
    if any(a.get(k) != b.get(k) for k in keys):
        return True
    if a.get("x") is None or b.get("x") is None:
        return a.get("x") != b.get("x")
    return abs(a["x"] - b["x"]) + abs(a["y"] - b["y"]) > 0.5


def _progress(a: Assignment | None, remaining: float | None) -> float | None:
    if a is None or remaining is None or a.length <= 0:
        return None
    return round(max(0.0, min(1.0, 1.0 - remaining / a.length)), 3)


def _compact_snapshot(snap: dict) -> dict:
    """Small replay frame: positions, hazards, KPIs, exits."""
    return {
        "kpis": snap["kpis"],
        "hazards": snap["hazards"],
        "exits": [{"node_id": e["node_id"], "assigned": e["assigned"], "queue": e["queue"]} for e in snap["exits"]],
        "devices": [
            [d["id"], d["kind"][0], d["x"], d["y"], d["level"], d["status"], d.get("goal")]
            for d in snap["devices"] if d.get("x") is not None
        ],
    }
