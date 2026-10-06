"""Assigns and maintains an evacuation route per person (real phone or simulated occupant).

Adaptive rerouting rules (paper §III-D "when congestion exceeds a set threshold ... compute
alternate paths", plus anti-oscillation safeguards the paper does not discuss):

* route becomes unsafe (fire on it / exit lost)     -> reroute immediately   (reason: hazard)
* person left their route (position jumped)          -> reroute immediately   (reason: deviation)
* congestion above threshold on the remaining route  -> consider a reroute, accepted only if
  it is at least ``reroute_improvement`` cheaper and the person's cooldown has passed
  (reason: congestion)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.congestion.density import congested_nodes
from app.routing.cache import RouteCache, congestion_fingerprint
from app.routing.graph import BuildingGraph
from app.routing.planner import (
    DEFAULT_PERSON,
    Person,
    RoutePlan,
    RoutingContext,
    path_cost,
    plan_route,
    remaining_path,
    static_route,
)


@dataclass
class Assignment:
    path: list[int]
    goal: int
    goal_type: str
    cost: float
    length: float
    assigned_at: float
    last_change: float
    reason: str
    version: int = 1


@dataclass
class RouteDecision:
    assignment: Assignment | None
    changed: bool
    reason: str


class EvacRouter:
    def __init__(self, graph: BuildingGraph, settings: dict, static: bool = False) -> None:
        self.graph = graph
        self.settings = settings
        self.static = static
        self.assignments: dict[str, Assignment] = {}
        self.ctx = RoutingContext.from_settings(settings)
        self.cache = RouteCache()
        self.hazard_version = 0
        self._ctx_key: tuple = ()
        self.reroute_count = {"hazard": 0, "congestion": 0, "deviation": 0}

    # ------------------------------------------------------------------ context

    def update_context(
        self,
        hazards: dict[int, str],
        congestion: dict[int, float],
        predicted: dict[int, float] | None,
        hazard_version: int,
        incident_active: bool = True,
    ) -> None:
        self.ctx.hazards = hazards
        self.ctx.congestion = congestion
        self.ctx.predicted_congestion = predicted or {}
        self.ctx.incident_active = incident_active
        self.hazard_version = hazard_version
        self._recount_exits()
        merged = {n: self.ctx.congestion_at(n) for n in set(congestion) | set(self.ctx.predicted_congestion)}
        exit_buckets = tuple(sorted((e, c // 5) for e, c in self.ctx.exit_assigned.items()))
        self._ctx_key = (hazard_version, congestion_fingerprint(merged), exit_buckets, incident_active)

    def _recount_exits(self) -> None:
        counts: dict[int, int] = {}
        for a in self.assignments.values():
            if a.goal_type == "exit":
                counts[a.goal] = counts.get(a.goal, 0) + 1
        self.ctx.exit_assigned = counts

    # ------------------------------------------------------------------ planning

    def _plan(self, start: int, person: Person, current_exit: int | None) -> RoutePlan | None:
        if self.static:
            fire = {n for n, lvl in self.ctx.hazards.items() if lvl == "fire"}
            return static_route(self.graph, start, person, fire)
        key = (start, person.stairs_ok, current_exit, self._ctx_key)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        plan = plan_route(self.graph, start, self.ctx, person, current_exit)
        if plan is not None:
            self.cache.put(key, plan)
        return plan

    def route(self, person_id: str, node_id: int, now: float, person: Person = DEFAULT_PERSON) -> RouteDecision:
        a = self.assignments.get(person_id)
        if a is None:
            return self._assign(person_id, node_id, now, person, "initial")

        rem = remaining_path(a.path, node_id)
        if not rem:
            return self._assign(person_id, node_id, now, person, "deviation", previous=a)

        if self.static:
            # static plans only change when the person runs into fire
            if any(self.ctx.hazards.get(n) == "fire" for n in rem[1:]) or self.ctx.hazards.get(a.goal) == "fire":
                return self._assign(person_id, node_id, now, person, "hazard", previous=a)
            return RouteDecision(a, False, "keep")

        current_cost = path_cost(self.graph, rem, self.ctx, person)
        if current_cost is None:
            return self._assign(person_id, node_id, now, person, "hazard", previous=a)

        threshold = float(self.settings.get("congestion_threshold", 0.8))
        merged = {n: self.ctx.congestion_at(n) for n in rem[1:]}
        if not congested_nodes(merged, threshold):
            return RouteDecision(a, False, "keep")

        cooldown = float(self.settings.get("reroute_cooldown_s", 10))
        if now - a.last_change < cooldown:
            return RouteDecision(a, False, "cooldown")
        candidate = self._plan(node_id, person, a.goal if a.goal_type == "exit" else None)
        improvement = float(self.settings.get("reroute_improvement", 0.15))
        if candidate is None or candidate.path == rem or candidate.cost >= current_cost * (1.0 - improvement):
            return RouteDecision(a, False, "keep")
        return self._store(person_id, candidate, now, "congestion", previous=a)

    def _assign(self, person_id: str, node_id: int, now: float, person: Person, reason: str, previous: Assignment | None = None) -> RouteDecision:
        plan = self._plan(node_id, person, previous.goal if previous and previous.goal_type == "exit" else None)
        if plan is None:
            self.assignments.pop(person_id, None)
            self._recount_exits()
            return RouteDecision(None, previous is not None, "no_route")
        return self._store(person_id, plan, now, reason, previous)

    def _store(self, person_id: str, plan: RoutePlan, now: float, reason: str, previous: Assignment | None = None) -> RouteDecision:
        if previous is not None and plan.path == remaining_path(previous.path, plan.path[0]):
            return RouteDecision(previous, False, "keep")
        a = Assignment(
            path=plan.path,
            goal=plan.goal,
            goal_type=plan.goal_type,
            cost=plan.cost,
            length=plan.length,
            assigned_at=previous.assigned_at if previous else now,
            last_change=now,
            reason=reason,
            version=(previous.version + 1) if previous else 1,
        )
        self.assignments[person_id] = a
        if previous is not None and reason in self.reroute_count:
            self.reroute_count[reason] += 1
        self._recount_exits()
        return RouteDecision(a, True, reason)

    def release(self, person_id: str) -> None:
        if self.assignments.pop(person_id, None) is not None:
            self._recount_exits()

    def remaining_routes(self, positions: dict[str, int]) -> list[list[int]]:
        out = []
        for pid, a in self.assignments.items():
            node = positions.get(pid)
            if node is not None:
                rem = remaining_path(a.path, node)
                if rem:
                    out.append(rem)
        return out
