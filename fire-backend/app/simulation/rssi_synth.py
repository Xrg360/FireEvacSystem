"""Synthetic Wi-Fi scans for virtual phones, from the log-distance path loss model + noise."""

from __future__ import annotations

import math

import numpy as np

from app.positioning.rssi import expected_rssi
from app.routing.graph import BuildingGraph

NOISE_DB = 4.0
FLOOR_ATTENUATION_DB = 15.0
SENSITIVITY_DBM = -92.0


def synth_scan(graph: BuildingGraph, x: float, y: float, level: int, rng: np.random.Generator) -> dict[str, float]:
    readings: dict[str, float] = {}
    for ap in graph.access_points:
        dz = (ap.level - level) * graph.floor_height
        d = math.sqrt((ap.x - x) ** 2 + (ap.y - y) ** 2 + dz**2)
        rssi = expected_rssi(d, ap.p_ref, ap.eta) - FLOOR_ATTENUATION_DB * abs(ap.level - level) + rng.normal(0, NOISE_DB)
        if rssi >= SENSITIVITY_DBM:
            readings[ap.bssid] = round(float(rssi), 1)
    return readings


def synth_survey(graph: BuildingGraph, scans_per_node: int, rng: np.random.Generator) -> list[tuple[int, dict[str, float]]]:
    """Simulated walk-through survey: labelled scans near every walkable node."""
    out = []
    for n in graph.nodes.values():
        if n.type == "assembly":
            continue
        for _ in range(scans_per_node):
            jx, jy = rng.normal(0, 0.8, 2)
            out.append((n.id, synth_scan(graph, n.x + jx, n.y + jy, n.level, rng)))
    return out
