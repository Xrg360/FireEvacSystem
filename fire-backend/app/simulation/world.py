"""Discrete-time evacuation simulator.

Virtual occupants walk the building graph, slow down in congested spaces (density-speed
relation), queue at exits limited by each exit's flow rate, and can be trapped by fire.
The same ``EvacRouter`` that serves real phones routes them, so the simulator exercises the
real decision logic. The benchmark runs it twice per scenario: static plan vs dynamic A*.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from app.congestion.density import congestion_ratios, occupancy
from app.engine.router import EvacRouter
from app.routing.graph import BuildingGraph
from app.routing.planner import Person
from app.simulation.fire import FireModel

TRAPPED_AFTER_S = 20.0


@dataclass
class Occupant:
    id: str
    node: int
    speed: float
    stairs_ok: bool = True
    is_phone: bool = False
    next_node: int | None = None
    progress: float = 0.0  # metres along the current edge
    edge_len: float = 0.0
    state: str = "idle"  # idle | evacuating | queued | safe | refuge | trapped
    evac_start: float | None = None
    done_at: float | None = None
    fire_exposure: float = 0.0
    last_scan: float = -1e9
    distance_walked: float = 0.0

    def position(self, graph: BuildingGraph) -> tuple[float, float, int]:
        a = graph.nodes[self.node]
        if self.next_node is None or self.edge_len <= 0:
            return a.x, a.y, a.level
        b = graph.nodes[self.next_node]
        f = min(self.progress / self.edge_len, 1.0)
        level = a.level if f < 0.5 else b.level
        return a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, level

    def location_node(self) -> int:
        """Node the person counts towards for occupancy."""
        if self.next_node is not None and self.edge_len > 0 and self.progress > self.edge_len / 2:
            return self.next_node
        return self.node

    @property
    def active(self) -> bool:
        return self.state in {"idle", "evacuating", "queued"}


@dataclass
class SimMetrics:
    evac_times: list[float] = field(default_factory=list)
    max_queue: dict[int, int] = field(default_factory=dict)
    queue_samples: list[int] = field(default_factory=list)
    trapped: int = 0
    refuge: int = 0


class Simulation:
    def __init__(
        self,
        graph: BuildingGraph,
        router: EvacRouter,
        rng: np.random.Generator | None = None,
        fire_spread_per_min: float = 0.6,
        predictor=None,
        fire_rng: np.random.Generator | None = None,
    ) -> None:
        self.graph = graph
        self.router = router
        self.rng = rng or np.random.default_rng()
        # separate stream so static and dynamic runs of one seed see the identical fire
        self.fire = FireModel(graph, fire_spread_per_min, fire_rng or np.random.default_rng())
        self.occupants: dict[str, Occupant] = {}
        self.t = 0.0
        self.alarm_t: float | None = None
        self.exit_queues: dict[int, deque[str]] = {e: deque() for e in graph.exits}
        self.exit_credit: dict[int, float] = {e: 0.0 for e in graph.exits}
        self.metrics = SimMetrics()
        self.predictor = predictor
        self.hazard_version = 0
        self._last_hazards: dict[int, str] = {}
        self.extra_hazards: dict[int, str] = {}  # sensor/manual hazards injected by the engine
        self.history: list[dict] = []  # optional per-tick node occupancy (ML training)
        self.record_history = False
        self.external_nodes: dict[str, int] = {}  # real phones sharing the building (engine)

    # ------------------------------------------------------------------ setup

    def spawn(self, n: int, phone_share: float = 0.0, mobility_share: float = 0.05, prefix: str = "sim") -> list[str]:
        rooms = [nid for nid, node in self.graph.nodes.items() if node.type in {"room", "corridor"}]
        weights = np.array([max(self.graph.nodes[r].capacity, 1) for r in rooms], dtype=float)
        weights /= weights.sum()
        ids = []
        start = len(self.occupants)
        for i in range(n):
            oid = f"{prefix}-{start + i + 1:03d}"
            node = int(self.rng.choice(rooms, p=weights))
            speed = float(np.clip(self.rng.normal(1.25, 0.25), 0.5, 1.8))
            stairs_ok = bool(self.rng.random() >= mobility_share)
            if not stairs_ok:
                speed *= 0.6
            self.occupants[oid] = Occupant(oid, node, speed, stairs_ok, bool(self.rng.random() < phone_share))
            ids.append(oid)
        return ids

    def start_alarm(self) -> None:
        """Sound the alarm; also used for occupants spawned after the alarm went off."""
        if self.alarm_t is None:
            self.alarm_t = self.t
        for o in self.occupants.values():
            if o.state == "idle":
                o.state = "evacuating"
                # reaction / pre-movement time: 0-20 s
                o.evac_start = self.t + float(self.rng.uniform(0, 20))

    # ------------------------------------------------------------------ hazards

    def hazards(self) -> dict[int, str]:
        hz = dict(self.fire.hazards())
        for n, lvl in self.extra_hazards.items():
            if lvl == "fire" or hz.get(n) not in {"fire", "smoke"}:
                hz[n] = lvl
        return hz

    # ------------------------------------------------------------------ step

    def node_occupancy(self) -> dict[int, int]:
        nodes = [o.location_node() for o in self.occupants.values() if o.active]
        nodes.extend(self.external_nodes.values())
        return occupancy(nodes)

    def step(self, dt: float) -> dict:
        self.t += dt
        newly = self.fire.step(self.t, dt)
        hazards = self.hazards()
        if hazards != self._last_hazards:
            self.hazard_version += 1
            self._last_hazards = hazards
        if self.fire.fire and self.alarm_t is None:
            self.start_alarm()

        occ = self.node_occupancy()
        ratios = congestion_ratios(self.graph, occ)
        positions = {o.id: o.node for o in self.occupants.values() if o.active}
        predicted = None
        if self.predictor is not None and self.alarm_t is not None:
            predicted = self.predictor.predict(self.graph, occ, self.router.remaining_routes(positions), self.t - self.alarm_t)
        self.router.update_context(hazards, ratios, predicted, self.hazard_version, incident_active=self.alarm_t is not None)

        if self.record_history and self.alarm_t is not None:
            through, nxt = _planned(self.router, positions)
            self.history.append({"t": self.t - self.alarm_t, "occ": occ, "through": through, "next": nxt})

        for o in self.occupants.values():
            if not o.active:
                continue
            # fire exposure
            here = o.location_node()
            if hazards.get(here) == "fire":
                o.fire_exposure += dt
                if o.fire_exposure >= TRAPPED_AFTER_S:
                    self._finish(o, "trapped")
                    continue
            if o.state != "evacuating" or (o.evac_start is not None and self.t < o.evac_start):
                continue
            self._advance(o, dt, ratios, hazards)

        self._process_exits(dt)
        return {"new_fire": newly}

    def _advance(self, o: Occupant, dt: float, ratios: dict[int, float], hazards: dict[int, str]) -> None:
        if o.next_node is None:
            node = self.graph.nodes[o.node]
            if node.type == "exit":
                self._enqueue(o)
                return
            if node.type == "refuge" and not o.stairs_ok:
                self._finish(o, "refuge")
                return
            decision = self.router.route(o.id, o.node, self.t, Person(o.stairs_ok))
            a = decision.assignment
            if a is None or len(a.path) < 2:
                if a is not None and a.goal == o.node:
                    if a.goal_type == "exit":
                        self._enqueue(o)
                    else:
                        self._finish(o, "refuge")
                return
            idx = a.path.index(o.node) if o.node in a.path else 0
            if idx + 1 >= len(a.path):
                return
            o.next_node = a.path[idx + 1]
            o.edge_len = self.graph.walk_length(o.node, o.next_node)
            o.progress = 0.0
        # speed falls with density in the space ahead (Fruin-style: free flow below 0.5)
        ratio = ratios.get(o.next_node, 0.0)
        factor = float(np.clip(1.0 - 0.55 * max(0.0, ratio - 0.5), 0.15, 1.0))
        edge = self.graph.edge_between(o.node, o.next_node)
        if edge is not None and edge.kind == "stair":
            factor *= 0.6
        if hazards.get(o.next_node) == "smoke":
            factor *= 0.7
        move = o.speed * factor * dt
        o.progress += move
        o.distance_walked += move
        if o.progress >= o.edge_len:
            o.node, o.next_node, o.progress, o.edge_len = o.next_node, None, 0.0, 0.0

    def _enqueue(self, o: Occupant) -> None:
        if o.state != "queued":
            o.state = "queued"
            self.exit_queues.setdefault(o.node, deque()).append(o.id)

    def _process_exits(self, dt: float) -> None:
        total_queue = 0
        for exit_id, q in self.exit_queues.items():
            flow = self.graph.nodes[exit_id].exit_flow_per_min or 40.0
            self.exit_credit[exit_id] = self.exit_credit.get(exit_id, 0.0) + flow / 60.0 * dt
            while q and self.exit_credit[exit_id] >= 1.0:
                oid = q.popleft()
                self.exit_credit[exit_id] -= 1.0
                o = self.occupants[oid]
                if o.state == "queued":
                    self._finish(o, "safe")
            if not q:
                self.exit_credit[exit_id] = min(self.exit_credit[exit_id], 1.0)
            self.metrics.max_queue[exit_id] = max(self.metrics.max_queue.get(exit_id, 0), len(q))
            total_queue += len(q)
        if self.alarm_t is not None:
            self.metrics.queue_samples.append(total_queue)

    def _finish(self, o: Occupant, state: str) -> None:
        o.state = state
        o.done_at = self.t
        o.next_node = None
        self.router.release(o.id)
        if state == "safe" and self.alarm_t is not None:
            self.metrics.evac_times.append(self.t - self.alarm_t)
        elif state == "trapped":
            self.metrics.trapped += 1
        elif state == "refuge":
            self.metrics.refuge += 1

    @property
    def finished(self) -> bool:
        return self.alarm_t is not None and not any(o.active for o in self.occupants.values())

    def summary(self) -> dict:
        times = self.metrics.evac_times
        q = self.metrics.queue_samples
        return {
            "occupants": len(self.occupants),
            "evacuated": len(times),
            "trapped": self.metrics.trapped,
            "in_refuge": self.metrics.refuge,
            "avg_evac_time_s": round(float(np.mean(times)), 1) if times else None,
            "max_evac_time_s": round(float(np.max(times)), 1) if times else None,
            "p90_evac_time_s": round(float(np.percentile(times, 90)), 1) if times else None,
            "avg_exit_queue": round(float(np.mean(q)), 2) if q else 0.0,
            "peak_exit_queue": max(self.metrics.max_queue.values(), default=0),
            "reroutes": dict(self.router.reroute_count),
            "sim_time_s": round(self.t - (self.alarm_t or 0.0), 1),
        }


def _planned(router: EvacRouter, positions: dict[str, int]) -> tuple[dict[int, int], dict[int, int]]:
    from app.congestion.predict import planned_counts

    return planned_counts(router.remaining_routes(positions))


def nearest_exit_distance(graph: BuildingGraph, node: int) -> float:
    return min((graph.lower_bound(node, e) for e in graph.exits), default=math.inf)
