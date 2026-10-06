"""Predictive congestion (paper Table II: "use historical data to anticipate congestion").

A gradient-boosted regressor predicts each node's occupancy ``HORIZON_S`` seconds ahead from:
  * the node's current occupancy and capacity,
  * occupancy of its neighbours (people about to arrive),
  * how many current routes pass through it (people *planned* to arrive),
  * whether it is an exit / stair, and time since the incident began.

Training data comes from simulator runs (``scripts/train_congestion.py``). Routing uses
max(current, predicted) so routes avoid bottlenecks before they form. Without a trained model
the predictor falls back to a transparent baseline (current occupancy + planned inflow share).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from app.routing.graph import BuildingGraph

HORIZON_S = 30.0
FEATURES = [
    "occ",
    "capacity",
    "occ_ratio",
    "neighbour_occ",
    "planned_through",
    "planned_next",
    "is_exit",
    "is_stair",
    "elapsed_s",
]


def node_features(
    graph: BuildingGraph,
    occ: dict[int, int],
    planned_through: dict[int, int],
    planned_next: dict[int, int],
    elapsed_s: float,
) -> tuple[list[int], np.ndarray]:
    ids = list(graph.nodes)
    rows = []
    for nid in ids:
        node = graph.nodes[nid]
        neighbours = [e.other(nid) for e in graph.adjacency[nid]]
        o = occ.get(nid, 0)
        rows.append(
            [
                o,
                node.capacity,
                o / max(node.capacity, 1),
                sum(occ.get(n, 0) for n in neighbours),
                planned_through.get(nid, 0),
                planned_next.get(nid, 0),
                1.0 if node.type == "exit" else 0.0,
                1.0 if node.type == "stair" else 0.0,
                elapsed_s,
            ]
        )
    return ids, np.asarray(rows, dtype=float)


def planned_counts(routes: list[list[int]]) -> tuple[dict[int, int], dict[int, int]]:
    """People whose remaining route passes through a node, and whose *next* node it is."""
    through: dict[int, int] = {}
    nxt: dict[int, int] = {}
    for path in routes:
        for nid in path[1:]:
            through[nid] = through.get(nid, 0) + 1
        if len(path) > 1:
            nxt[path[1]] = nxt.get(path[1], 0) + 1
    return through, nxt


@dataclass
class CongestionPredictor:
    model: object | None = None
    version: str = "baseline"

    @classmethod
    def load(cls, model_dir: Path) -> CongestionPredictor:
        path = model_dir / "congestion.joblib"
        if path.exists():
            bundle = joblib.load(path)
            return cls(bundle["model"], bundle.get("version", "gbr"))
        return cls()

    def predict(
        self,
        graph: BuildingGraph,
        occ: dict[int, int],
        routes: list[list[int]],
        elapsed_s: float,
    ) -> dict[int, float]:
        """Predicted occupancy / capacity ratio per node, HORIZON_S seconds ahead."""
        through, nxt = planned_counts(routes)
        ids, X = node_features(graph, occ, through, nxt, elapsed_s)
        if self.model is not None:
            pred = np.maximum(self.model.predict(X), 0.0)
        else:
            # baseline: people already here + half of those heading here next
            pred = X[:, 0] + 0.5 * X[:, 5]
        caps = np.maximum(X[:, 1], 1.0)
        return {nid: float(p / c) for nid, p, c in zip(ids, pred, caps, strict=True) if p > 0}
