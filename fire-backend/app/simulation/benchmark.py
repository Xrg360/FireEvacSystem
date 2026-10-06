"""Reproducible evaluation (paper §VII, Table I).

Static evacuation plan vs the proposed dynamic A* routing, on identical scenarios
(same occupants, same reaction times, same fire spread), plus positioning accuracy.

    python -m app.simulation.benchmark --seeds 20
    python -m app.simulation.benchmark --building block_a_villa --occupants 40 --fire A-KITCHEN
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np

from app.congestion.predict import CongestionPredictor
from app.engine.router import EvacRouter
from app.models import DEFAULT_BUILDING_SETTINGS
from app.positioning import fingerprint as fp
from app.positioning.fallback import new_locator
from app.positioning.particle_filter import PFMap
from app.positioning.trilateration import match_observations, triangulate
from app.routing.graph import BuildingGraph
from app.routing.planner import Person, RoutingContext, plan_route
from app.simulation.rssi_synth import synth_scan, synth_survey
from app.simulation.world import Simulation

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"

DEFAULT_SCENARIOS = {
    "block_b_tower": {"occupants": 150, "fire": ["B1-F02"], "spread": 0.8},
    "block_a_villa": {"occupants": 30, "fire": ["A-KITCHEN"], "spread": 0.6},
}


def load_graph(name: str) -> BuildingGraph:
    return BuildingGraph.from_dict(json.loads((FIXTURES / f"{name}.json").read_text()))


def run_once(graph: BuildingGraph, seed: int, occupants: int, fire_keys: list[str], spread: float, mode: str,
             predictor: CongestionPredictor | None = None, max_t: float = 1200.0, dt: float = 0.5) -> dict:
    settings = dict(DEFAULT_BUILDING_SETTINGS)
    router = EvacRouter(graph, settings, static=(mode == "static"))
    sim = Simulation(
        graph, router, rng=np.random.default_rng(seed), fire_spread_per_min=spread,
        predictor=predictor if mode == "dynamic" else None, fire_rng=np.random.default_rng(seed + 10_000),
    )
    sim.spawn(occupants)
    for key in fire_keys:
        sim.fire.ignite(graph.node_by_key(key).id, 0.0)
    while not sim.finished and sim.t < max_t:
        sim.step(dt)
    return sim.summary()


def replan_latency_ms(graph: BuildingGraph, fire_keys: list[str], people: int = 200) -> float:
    """Time to recompute every person's route after a hazard change (server side)."""
    rng = np.random.default_rng(1)
    starts = [n for n, node in graph.nodes.items() if node.type in {"room", "corridor"}]
    ctx = RoutingContext.from_settings(DEFAULT_BUILDING_SETTINGS, hazards={graph.node_by_key(k).id: "fire" for k in fire_keys})
    picks = rng.choice(starts, size=people)
    t0 = time.perf_counter()
    for s in picks:
        plan_route(graph, int(s), ctx, Person())
    return (time.perf_counter() - t0) * 1000.0


def positioning_benchmark(graph: BuildingGraph, seed: int = 3, test_points: int = 150) -> dict:
    """Localization error on synthetic scans: trilateration only, fingerprint only, fused particle filter."""
    rng = np.random.default_rng(seed)
    model = fp.train(synth_survey(graph, 15, rng))
    nodes = [n for n in graph.nodes.values() if n.type != "assembly"]
    pf_map = PFMap(graph)
    tri_err, fp_err, pf_err, floor_ok = [], [], [], 0
    for i in range(test_points):
        node = nodes[int(rng.integers(len(nodes)))]
        tx, ty = node.x + rng.normal(0, 1.0), node.y + rng.normal(0, 1.0)
        level = node.level
        tri = triangulate(match_observations(synth_scan(graph, tx, ty, level, rng), graph.access_points))
        if tri:
            tri_err.append(np.hypot(tri.x - tx, tri.y - ty) + graph.floor_height * abs(tri.level - level))
        probs = model.predict_proba(synth_scan(graph, tx, ty, level, rng)) if model else {}
        if probs:
            best = graph.nodes[max(probs, key=probs.get)]
            fp_err.append(np.hypot(best.x - tx, best.y - ty) + graph.floor_height * abs(best.level - level))
        # particle filter: a person standing still, 4 scans ~3 s apart (scan throttling disabled)
        loc = new_locator(f"t{i}", pf_map, 400, seed=seed + i)
        est = None
        for k in range(4):
            est = loc.on_scan(synth_scan(graph, tx, ty, level, rng), k * 3.0, model, DEFAULT_BUILDING_SETTINGS["rssi_uncertainty_db"])
        if est:
            pf_err.append(np.hypot(est.x - tx, est.y - ty) + graph.floor_height * abs(est.level - level))
            floor_ok += int(est.level == level)

    def stats(errs: list[float]) -> dict:
        if not errs:
            return {"mean_m": None, "median_m": None, "p90_m": None}
        return {"mean_m": round(float(np.mean(errs)), 2), "median_m": round(float(np.median(errs)), 2), "p90_m": round(float(np.percentile(errs, 90)), 2)}

    return {
        "trilateration": stats(tri_err),
        "fingerprint_knn": stats(fp_err),
        "particle_filter_fused": stats(pf_err),
        "pf_floor_accuracy": round(floor_ok / max(len(pf_err), 1), 3),
        "test_points": test_points,
        "note": "Synthetic scans: log-distance path loss, 4 dB noise, 15 dB per floor. Real buildings are noisier.",
    }


def compare(name: str, seeds: int, occupants: int | None = None, fire: list[str] | None = None, spread: float | None = None,
            use_predictor: bool = False) -> dict:
    graph = load_graph(name)
    sc = DEFAULT_SCENARIOS.get(name, {"occupants": 50, "fire": [], "spread": 0.6})
    return compare_graph(
        graph, seeds, occupants or sc["occupants"], fire or sc["fire"], sc["spread"] if spread is None else spread, use_predictor, name
    )


def compare_graph(graph: BuildingGraph, seeds: int, occupants: int, fire: list[str], spread: float, use_predictor: bool = False,
                  name: str | None = None) -> dict:
    predictor = CongestionPredictor.load(Path(__file__).resolve().parents[2] / "ml_models") if use_predictor else None
    rows = {"static": [], "dynamic": []}
    for s in range(seeds):
        for mode in ("static", "dynamic"):
            rows[mode].append(run_once(graph, s, occupants, fire, spread, mode, predictor))

    def agg(mode: str, key: str):
        vals = [r[key] for r in rows[mode] if r[key] is not None]
        return round(statistics.mean(vals), 2) if vals else None

    keys = ["avg_evac_time_s", "p90_evac_time_s", "max_evac_time_s", "avg_exit_queue", "peak_exit_queue", "trapped", "in_refuge"]
    table = {k: {"static": agg("static", k), "dynamic": agg("dynamic", k)} for k in keys}
    sq, dq = table["avg_exit_queue"]["static"], table["avg_exit_queue"]["dynamic"]
    queue_reduction = round(100.0 * (sq - dq) / sq, 1) if sq else None
    st, dy = table["avg_evac_time_s"]["static"], table["avg_evac_time_s"]["dynamic"]
    return {
        "building": name or graph.name,
        "occupants": occupants,
        "fire_start": fire,
        "seeds": seeds,
        "predictor": (predictor.version if predictor else "none"),
        "table": table,
        "exit_queue_reduction_pct": queue_reduction,
        "evac_time_reduction_pct": round(100.0 * (st - dy) / st, 1) if st and dy else None,
        "replan_latency_ms_200_people": round(replan_latency_ms(graph, fire), 1),
        "positioning": positioning_benchmark(graph) if graph.access_points else None,
    }


def to_markdown(result: dict) -> str:
    t = result["table"]
    lines = [
        f"### {result['building']} - {result['occupants']} occupants, fire at {', '.join(result['fire_start'])}, {result['seeds']} seeds",
        "",
        "| Metric | Static plan | Proposed (dynamic A*) |",
        "|---|---|---|",
    ]
    labels = {
        "avg_evac_time_s": "Average evacuation time (s)",
        "p90_evac_time_s": "90th percentile evacuation time (s)",
        "max_evac_time_s": "Total evacuation time (s)",
        "avg_exit_queue": "Average exit queue (people)",
        "peak_exit_queue": "Peak exit queue (people)",
        "trapped": "Trapped by fire",
        "in_refuge": "Sheltering in refuge area",
    }
    for k, label in labels.items():
        lines.append(f"| {label} | {t[k]['static']} | {t[k]['dynamic']} |")
    lines.append(f"| Exit queue reduction | - | {result['exit_queue_reduction_pct']}% |")
    lines.append(f"| Server route recomputation, 200 people | N/A | {result['replan_latency_ms_200_people']} ms |")
    p = result["positioning"]
    if not p:
        return "\n".join(lines)
    lines.append(f"| Localization error, fused PF (median / p90) | - | {p['particle_filter_fused']['median_m']} m / {p['particle_filter_fused']['p90_m']} m |")
    lines.append(f"| Localization error, trilateration only (median) | - | {p['trilateration']['median_m']} m |")
    lines.append(f"| Localization error, fingerprint kNN only (median) | - | {p['fingerprint_knn']['median_m']} m |")
    lines.append(f"| Floor identified correctly (PF) | - | {round(100 * p['pf_floor_accuracy'], 1)}% |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--building", action="append", help="fixture name (default: both demo blocks)")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--occupants", type=int)
    ap.add_argument("--fire", action="append", help="node key where the fire starts")
    ap.add_argument("--spread", type=float)
    ap.add_argument("--predictor", action="store_true", help="use the trained congestion predictor")
    ap.add_argument("--json", type=Path, help="write raw results to this file")
    args = ap.parse_args()
    results = [compare(b, args.seeds, args.occupants, args.fire, args.spread, args.predictor) for b in (args.building or list(DEFAULT_SCENARIOS))]
    for r in results:
        print(to_markdown(r))
        print()
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
