"""Train the predictive congestion model (paper Table II "predictive congestion handling").

Runs many simulated evacuations (varied crowd sizes, fire locations, seeds) with the baseline
predictor, records each node's features every tick, and learns occupancy HORIZON_S seconds ahead.
Evaluated on held-out *scenarios* (not random ticks) against two baselines.

    python -m scripts.train_congestion --runs 40
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from app.congestion.predict import FEATURES, HORIZON_S, CongestionPredictor, node_features
from app.engine.router import EvacRouter
from app.models import DEFAULT_BUILDING_SETTINGS
from app.simulation.benchmark import load_graph
from app.simulation.world import Simulation

DT = 0.5
MODEL_DIR = Path(__file__).resolve().parent.parent / "ml_models"


def collect(graph_name: str, seed: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    graph = load_graph(graph_name)
    router = EvacRouter(graph, dict(DEFAULT_BUILDING_SETTINGS))
    sim = Simulation(graph, router, rng=np.random.default_rng(seed), fire_spread_per_min=float(rng.uniform(0.3, 1.2)),
                     predictor=CongestionPredictor(), fire_rng=np.random.default_rng(seed + 99))
    rooms = [n.key for n in graph.nodes.values() if n.type in {"room", "corridor"}]
    sim.spawn(int(rng.integers(40, 220 if "tower" in graph_name else 45)))
    sim.fire.ignite(graph.node_by_key(rooms[int(rng.integers(len(rooms)))]).id, 0.0)
    sim.record_history = True
    while not sim.finished and sim.t < 900:
        sim.step(DT)
    h = sim.history
    lag = int(HORIZON_S / DT)
    X, y, base = [], [], []
    for i in range(0, len(h) - lag, 2):
        ids, feats = node_features(graph, h[i]["occ"], h[i]["through"], h[i]["next"], h[i]["t"])
        future = h[i + lag]["occ"]
        X.append(feats)
        y.append([future.get(n, 0) for n in ids])
        base.append(feats[:, 0])  # persistence baseline: occupancy stays the same
    if not X:
        return np.empty((0, len(FEATURES))), np.empty(0), np.empty(0)
    return np.vstack(X), np.concatenate(y), np.concatenate(base)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=40)
    args = ap.parse_args()
    rng = np.random.default_rng(2025)
    data = []
    for r in range(args.runs):
        name = "block_b_tower" if r % 4 else "block_a_villa"
        data.append(collect(name, r, rng))
        print(f"run {r + 1}/{args.runs} {name}: {len(data[-1][1])} samples")
    split = int(len(data) * 0.8)
    X_tr = np.vstack([d[0] for d in data[:split]])
    y_tr = np.concatenate([d[1] for d in data[:split]])
    X_te = np.vstack([d[0] for d in data[split:]])
    y_te = np.concatenate([d[1] for d in data[split:]])
    persist = np.concatenate([d[2] for d in data[split:]])
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08, max_leaf_nodes=31, random_state=0)
    model.fit(X_tr, y_tr)
    pred = np.maximum(model.predict(X_te), 0)
    planned = X_te[:, 0] + 0.5 * X_te[:, 5]
    report = {
        "train_samples": int(len(y_tr)),
        "test_samples": int(len(y_te)),
        "mae_model": round(float(mean_absolute_error(y_te, pred)), 3),
        "mae_persistence_baseline": round(float(mean_absolute_error(y_te, persist)), 3),
        "mae_planned_inflow_baseline": round(float(mean_absolute_error(y_te, planned)), 3),
        "horizon_s": HORIZON_S,
        "features": FEATURES,
    }
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump({"model": model, "version": "hgbr-v1", "report": report}, MODEL_DIR / "congestion.joblib")
    print("\nHeld-out scenario evaluation (people per node, 30 s ahead):")
    for k, v in report.items():
        print(f"  {k}: {v}")
    print(f"\nsaved {MODEL_DIR / 'congestion.joblib'}")


if __name__ == "__main__":
    main()
