"""Hazard- and congestion-aware route planning on top of A*.

Edge cost (paper §III-C/D, §VI):
    cost = length * (1 + alpha*hazard(v) + beta*congestion(v)) + gamma*exit_wait(v)

* nodes on fire are pruned (Alg. 2 line 6), as are lifts during an incident;
* hazard: risk=0.25, smoke=1.0 (multiplied by alpha);
* congestion: max(current, predicted) occupancy/capacity ratio, multiplied by beta;
* exit_wait: people already assigned to an exit / its flow rate, converted from minutes of
  waiting into equivalent walking metres (1.2 m/s), multiplied by gamma. This spreads people
  across exits by capacity (paper Table I "exit queue reduction").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.routing.astar import PathResult, astar
from app.routing.graph import BuildingGraph, GEdge

HAZARD_WEIGHT = {"none": 0.0, "risk": 0.25, "smoke": 1.0, "fire": None}
WALK_SPEED_MS = 1.2
DEFAULT_EXIT_FLOW_PER_MIN = 40.0


@dataclass
class RoutingContext:
    hazards: dict[int, str] = field(default_factory=dict)
    congestion: dict[int, float] = field(default_factory=dict)  # occupancy / capacity
    predicted_congestion: dict[int, float] = field(default_factory=dict)
    exit_assigned: dict[int, int] = field(default_factory=dict)  # exit node -> people assigned
    incident_active: bool = True
    alpha: float = 4.0
    beta: float = 2.0
    gamma: float = 1.0

    @classmethod
    def from_settings(cls, settings: dict, **kwargs) -> RoutingContext:
        return cls(
            alpha=float(settings.get("alpha", 4.0)),
            beta=float(settings.get("beta", 2.0)),
            gamma=float(settings.get("gamma", 1.0)),
            **kwargs,
        )

    def congestion_at(self, node_id: int) -> float:
        return max(self.congestion.get(node_id, 0.0), self.predicted_congestion.get(node_id, 0.0))


@dataclass(frozen=True)
class Person:
    stairs_ok: bool = True


DEFAULT_PERSON = Person()


@dataclass(frozen=True)
class RoutePlan:
    path: list[int]
    cost: float
    length: float
    goal_type: str  # exit | refuge

    @property
    def goal(self) -> int:
        return self.path[-1]


def make_cost_fn(graph: BuildingGraph, ctx: RoutingContext, person: Person, ignore_exit_load_for: int | None = None):
    def cost(edge: GEdge, _from: int, to: int) -> float | None:
        hazard = HAZARD_WEIGHT.get(ctx.hazards.get(to, "none"), 0.0)
        if hazard is None:
            return None
        if ctx.incident_active and edge.kind == "lift":
            return None
        if not person.stairs_ok and (edge.kind == "stair" or not edge.accessible):
            return None
        cong = min(ctx.congestion_at(to), 3.0)
        c = edge.length * (1.0 + ctx.alpha * hazard + ctx.beta * cong)
        node = graph.nodes[to]
        if node.type == "exit" and ctx.gamma > 0:
            assigned = ctx.exit_assigned.get(to, 0)
            if to == ignore_exit_load_for:
                assigned = max(0, assigned - 1)  # don't count the person against their own exit
            flow = node.exit_flow_per_min or DEFAULT_EXIT_FLOW_PER_MIN
            wait_min = assigned / flow
            c += ctx.gamma * wait_min * 60.0 * WALK_SPEED_MS
        return c

    return cost


def plan_route(
    graph: BuildingGraph,
    start: int,
    ctx: RoutingContext,
    person: Person = DEFAULT_PERSON,
    current_exit: int | None = None,
) -> RoutePlan | None:
    """Best route to an exit; residents who can't use stairs fall back to a refuge area."""
    blocked = {nid for nid, lvl in ctx.hazards.items() if lvl == "fire" and nid != start}
    cost_fn = make_cost_fn(graph, ctx, person, ignore_exit_load_for=current_exit)
    result = astar(graph, start, graph.exits, cost_fn, blocked)
    if result is not None:
        return _plan(result, "exit")
    if graph.refuges:
        result = astar(graph, start, graph.refuges, cost_fn, blocked)
        if result is not None:
            return _plan(result, "refuge")
    return None


def _plan(result: PathResult, goal_type: str) -> RoutePlan:
    return RoutePlan(result.path, result.cost, result.length, goal_type)


def path_cost(graph: BuildingGraph, path: list[int], ctx: RoutingContext, person: Person = DEFAULT_PERSON) -> float | None:
    """Cost of an existing path under current conditions; None if it is no longer safe."""
    if not path:
        return None
    cost_fn = make_cost_fn(graph, ctx, person, ignore_exit_load_for=path[-1])
    total = 0.0
    for a, b in zip(path, path[1:], strict=False):
        edge = graph.edge_between(a, b)
        if edge is None:
            return None
        step = cost_fn(edge, a, b)
        if step is None:
            return None
        total += step
    return total


def remaining_path(path: list[int], current: int) -> list[int]:
    if current in path:
        return path[path.index(current):]
    return []


def static_route(graph: BuildingGraph, start: int, person: Person = DEFAULT_PERSON, fire: set[int] | None = None) -> RoutePlan | None:
    """Baseline 'static evacuation plan': nearest exit by plain distance, no congestion awareness.

    ``fire`` lets the baseline react to fire it has run into (people see flames and turn back),
    which is how a static printed plan is followed in practice.
    """
    ctx = RoutingContext(hazards={n: "fire" for n in (fire or set())}, alpha=0.0, beta=0.0, gamma=0.0)
    return plan_route(graph, start, ctx, person)
