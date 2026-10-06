"""Real-time occupancy and congestion (paper §III-D: "user density is estimated via frequent
location updates; when congestion exceeds a set threshold, the affected area's cost increases")."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.routing.graph import BuildingGraph


def occupancy(node_ids: Iterable[int | None]) -> dict[int, int]:
    return dict(Counter(n for n in node_ids if n is not None))


def congestion_ratios(graph: BuildingGraph, occ: dict[int, int]) -> dict[int, float]:
    return {nid: count / max(graph.nodes[nid].capacity, 1) for nid, count in occ.items() if nid in graph.nodes}


def congested_nodes(ratios: dict[int, float], threshold: float) -> set[int]:
    return {nid for nid, r in ratios.items() if r >= threshold}


def congestion_rate(graph: BuildingGraph, ratios: dict[int, float], threshold: float) -> float:
    """Share of walkable nodes that are congested (dashboard KPI). 0 when the graph is empty."""
    walkable = [n for n in graph.nodes.values() if n.type not in {"assembly"}]
    if not walkable:
        return 0.0
    return len(congested_nodes(ratios, threshold)) / len(walkable)
