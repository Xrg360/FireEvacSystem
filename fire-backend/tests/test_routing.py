"""A* (paper Alg. 2) correctness: optimality, hazard pruning, level-aware routing, mobility."""

import heapq
import itertools
import json
from pathlib import Path

import pytest

from app.engine.router import EvacRouter
from app.models import DEFAULT_BUILDING_SETTINGS
from app.routing.astar import astar, plain_length_cost
from app.routing.graph import BuildingGraph, validate_graph
from app.routing.planner import Person, RoutingContext, make_cost_fn, plan_route
from app.routing.steps import build_steps

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"


def dijkstra(graph, start, goals, cost_fn):
    dist = {start: 0.0}
    heap = [(0.0, start)]
    while heap:
        d, n = heapq.heappop(heap)
        if n in goals:
            return d
        if d > dist.get(n, float("inf")):
            continue
        for e in graph.adjacency[n]:
            o = e.other(n)
            c = cost_fn(e, n, o)
            if c is None:
                continue
            if d + c < dist.get(o, float("inf")):
                dist[o] = d + c
                heapq.heappush(heap, (d + c, o))
    return None


@pytest.mark.parametrize("fixture", ["villa", "tower"])
def test_astar_matches_dijkstra_everywhere(fixture, request):
    graph = request.getfixturevalue(fixture)
    for start in graph.nodes:
        r = astar(graph, start, graph.exits, plain_length_cost)
        d = dijkstra(graph, start, set(graph.exits), plain_length_cost)
        assert r is not None and d is not None
        assert r.cost == pytest.approx(d, rel=1e-9)


def test_astar_optimal_with_hazard_and_congestion_costs(tower):
    ctx = RoutingContext(
        hazards={tower.node_by_key("B2-C1").id: "smoke", tower.node_by_key("B1-C3").id: "risk"},
        congestion={tower.node_by_key("B3-C2").id: 1.5, tower.node_by_key("B0-LIFT").id: 2.0},
        exit_assigned={tower.node_by_key("B0-EXIT-MAIN").id: 40},
    )
    cost_fn = make_cost_fn(tower, ctx, Person())
    for start in tower.nodes:
        r = astar(tower, start, tower.exits, cost_fn)
        d = dijkstra(tower, start, set(tower.exits), cost_fn)
        assert (r is None) == (d is None)
        if r:
            assert r.cost == pytest.approx(d, rel=1e-9)


def test_heuristic_is_admissible(tower):
    for a, b in itertools.product(list(tower.nodes)[:20], tower.exits):
        true = dijkstra(tower, a, {b}, plain_length_cost)
        assert tower.lower_bound(a, b) <= true + 1e-9


def test_paper_fig3_paths(villa):
    # Fig. 3: with fire in the kitchen and toilet, Toilet2 -> Living Room -> Verandah -> Entrance
    ctx = RoutingContext(hazards={villa.node_by_key("A-KITCHEN").id: "fire", villa.node_by_key("A-TOILET").id: "fire"})
    r = plan_route(villa, villa.node_by_key("A-TOILET2").id, ctx)
    assert [villa.nodes[n].name for n in r.path] == ["Toilet2", "Living Room", "Verandah", "Entrance"]


def test_fire_nodes_are_never_on_route(villa):
    fire = villa.node_by_key("A-VERANDAH").id
    ctx = RoutingContext(hazards={fire: "fire"})
    r = plan_route(villa, villa.node_by_key("A-LIVING").id, ctx)
    assert fire not in r.path
    assert villa.nodes[r.goal].type == "exit"


def test_exit_on_fire_is_not_a_goal(villa):
    entrance = villa.node_by_key("A-ENTRANCE").id
    r = plan_route(villa, villa.node_by_key("A-VERANDAH").id, RoutingContext(hazards={entrance: "fire"}))
    assert r.goal != entrance


def test_lifts_excluded_during_incident(tower):
    r = plan_route(tower, tower.node_by_key("B3-LIFT").id, RoutingContext(incident_active=True))
    kinds = {tower.edge_between(a, b).kind for a, b in zip(r.path, r.path[1:], strict=False)}
    assert "lift" not in kinds


def test_mobility_impaired_go_to_refuge_on_upper_floor(tower):
    r = plan_route(tower, tower.node_by_key("B2-F04").id, RoutingContext(), Person(stairs_ok=False))
    assert r.goal_type == "refuge"
    assert tower.nodes[r.goal].level == 2


def test_mobility_impaired_on_ground_floor_reach_exit(tower):
    r = plan_route(tower, tower.node_by_key("B0-LOBBY").id, RoutingContext(), Person(stairs_ok=False))
    assert r.goal_type == "exit"


def test_trapped_returns_none(villa):
    # surround the Bedroom: dining and balcony2 on fire
    ctx = RoutingContext(hazards={villa.node_by_key("A-DINING").id: "fire", villa.node_by_key("A-BALCONY2").id: "fire"})
    assert plan_route(villa, villa.node_by_key("A-BEDROOM").id, ctx) is None


def test_steps_collapse_stair_runs(tower):
    r = plan_route(tower, tower.node_by_key("B3-F02").id, RoutingContext())
    steps = build_steps(tower, r.path)
    stair_steps = [s for s in steps if s["kind"] == "stairs"]
    assert len(stair_steps) == 1 and "down to Ground Floor" in stair_steps[0]["text"]
    assert steps[-1]["kind"] == "exit"


def test_validation_flags_problems():
    data = json.loads((FIXTURES / "block_a_villa.json").read_text())
    data["edges"] = [e for e in data["edges"] if e["b"] != 9 and e["a"] != 9]  # isolate Toilet
    problems = validate_graph(BuildingGraph.from_dict(data))
    assert any("Toilet" in p for p in problems)


def test_router_exit_balancing_spreads_load(tower):
    router = EvacRouter(tower, dict(DEFAULT_BUILDING_SETTINGS))
    router.update_context({}, {}, None, 1)
    start = tower.node_by_key("B0-LOBBY").id
    goals = []
    for i in range(80):
        d = router.route(f"p{i}", start, 0.0)
        goals.append(d.assignment.goal)
        router.update_context({}, {}, None, 1)
    assert len(set(goals)) >= 2, "all 80 people were sent to the same exit"


def test_router_reroutes_on_new_fire_with_hazard_reason(villa):
    router = EvacRouter(villa, dict(DEFAULT_BUILDING_SETTINGS))
    router.update_context({}, {}, None, 1)
    start = villa.node_by_key("A-LIVING").id
    first = router.route("p", start, 0.0).assignment
    blocked = first.path[1]
    router.update_context({blocked: "fire"}, {}, None, 2)
    d = router.route("p", start, 1.0)
    assert d.changed and d.reason == "hazard" and blocked not in d.assignment.path


def test_router_congestion_cooldown(villa):
    settings = dict(DEFAULT_BUILDING_SETTINGS, reroute_cooldown_s=30)
    router = EvacRouter(villa, settings)
    router.update_context({}, {}, None, 1)
    start = villa.node_by_key("A-LIVING").id
    first = router.route("p", start, 0.0).assignment
    jam = {n: 3.0 for n in first.path[1:-1]}
    router.update_context({}, jam, None, 1)
    assert router.route("p", start, 5.0).reason in {"cooldown", "keep"}
