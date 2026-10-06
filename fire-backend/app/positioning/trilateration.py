"""Weighted triangulation (paper §V-D, Algorithm 3).

Each detected router with a known position contributes its coordinates, weighted by the
inverse square of the RSSI-estimated distance. The floor is the weighted vote of routers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.positioning.rssi import estimate_distance
from app.routing.graph import GAccessPoint


@dataclass(frozen=True)
class Observation:
    ap: GAccessPoint
    rssi: float


@dataclass(frozen=True)
class TriangulationResult:
    x: float
    y: float
    level: int
    weight: float
    used: int


def match_observations(readings: dict[str, float], access_points: list[GAccessPoint]) -> list[Observation]:
    index = {ap.bssid: ap for ap in access_points}
    out = []
    for bssid, rssi in readings.items():
        ap = index.get(bssid.lower())
        if ap is not None and rssi is not None and -100 < rssi < 0:
            out.append(Observation(ap, float(rssi)))
    return out


def triangulate(observations: list[Observation], max_aps: int = 6) -> TriangulationResult | None:
    if not observations:
        return None
    strongest = sorted(observations, key=lambda o: o.rssi, reverse=True)[:max_aps]

    # floor vote
    floor_weight: dict[int, float] = defaultdict(float)
    for o in strongest:
        d = estimate_distance(o.rssi, o.ap.p_ref, o.ap.eta)
        floor_weight[o.ap.level] += 1.0 / max(d, 0.5) ** 2
    level = max(floor_weight, key=floor_weight.get)

    # 1: initialise total weighted contributions
    sum_x = sum_y = total = 0.0
    used = 0
    # 2: for each detected router
    for o in strongest:
        if o.ap.level != level:
            continue
        d = estimate_distance(o.rssi, o.ap.p_ref, o.ap.eta)
        w = 1.0 / max(d, 0.5) ** 2
        # 3: weighted contributions of X and Y; 4: accumulate total weights
        sum_x += w * o.ap.x
        sum_y += w * o.ap.y
        total += w
        used += 1
    if total == 0:
        return None
    # 6: estimated X, Y as weighted averages; 7: return
    return TriangulationResult(sum_x / total, sum_y / total, level, total, used)
