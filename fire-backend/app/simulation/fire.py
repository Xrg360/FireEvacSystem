"""Probabilistic fire and smoke spread over the building graph (simulation mode only)."""

from __future__ import annotations

import math

import numpy as np

from app.routing.graph import BuildingGraph


class FireModel:
    def __init__(self, graph: BuildingGraph, spread_per_min: float = 0.6, rng: np.random.Generator | None = None) -> None:
        """``spread_per_min``: expected ignitions per minute along one open passage."""
        self.graph = graph
        self.rate = spread_per_min / 60.0
        self.rng = rng or np.random.default_rng()
        self.fire: dict[int, float] = {}  # node -> time it ignited

    def ignite(self, node_id: int, t: float) -> None:
        if node_id in self.graph.nodes and node_id not in self.fire:
            self.fire[node_id] = t

    def extinguish(self, node_id: int) -> None:
        self.fire.pop(node_id, None)

    def step(self, t: float, dt: float) -> set[int]:
        """Advance spread; returns newly ignited nodes."""
        if self.rate <= 0 or not self.fire:
            return set()
        new: set[int] = set()
        for nid in list(self.fire):
            for edge in self.graph.adjacency[nid]:
                other = edge.other(nid)
                if other in self.fire or other in new or self.graph.nodes[other].type in {"assembly"}:
                    continue
                rate = self.rate
                if edge.kind == "stair":
                    up = self.graph.nodes[other].level > self.graph.nodes[nid].level
                    rate *= 0.8 if up else 0.2  # fire and smoke climb stair cores
                elif edge.kind == "door":
                    rate *= 0.6  # doors slow spread
                elif edge.kind == "outdoor":
                    continue
                if self.rng.random() < 1.0 - math.exp(-rate * dt):
                    new.add(other)
        for nid in new:
            self.fire[nid] = t
        return new

    def hazards(self) -> dict[int, str]:
        """fire nodes, smoke around them, risk one step further."""
        return hazards_from_fire(self.graph, set(self.fire))


def hazards_from_fire(graph: BuildingGraph, fire: set[int]) -> dict[int, str]:
    """Fire nodes, smoke in adjacent spaces, risk one step further (never across outdoor edges)."""
    out: dict[int, str] = {n: "fire" for n in fire}
    smoke: set[int] = set()
    for nid in fire:
        for e in graph.adjacency[nid]:
            o = e.other(nid)
            if e.kind != "outdoor" and o not in out:
                smoke.add(o)
    for o in smoke:
        out[o] = "smoke"
    for nid in smoke:
        for e in graph.adjacency[nid]:
            o = e.other(nid)
            if e.kind != "outdoor" and o not in out:
                out[o] = "risk"
    return out
