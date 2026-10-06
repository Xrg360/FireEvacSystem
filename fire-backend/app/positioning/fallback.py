"""Location source arbitration: Wi-Fi particle filter -> GPS (coarse) -> manual pick.

* Wi-Fi particle filter is primary.
* A manual "Where are you?" pick is a strong observation: the particle filter is re-seeded
  at that node and the pick overrides other sources for ``MANUAL_HOLD_S`` seconds.
* GPS/fused location is only used for block-level decisions: is the person outside the
  building footprint, and are they near an assembly point (suggest "Are you safe?").
  GPS never sets a room or a floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.positioning import fingerprint as fp
from app.positioning.particle_filter import Estimate, ParticleFilter, PFMap
from app.positioning.trilateration import match_observations

MANUAL_HOLD_S = 60.0
WIFI_STALE_S = 45.0  # Android throttles foreground scans to 4 per 2 minutes
FLOOR_CONFIRM_COOLDOWN_S = 120.0
ASSEMBLY_RADIUS_M = 40.0


@dataclass
class GpsFix:
    lat: float
    lng: float
    accuracy_m: float
    ts: float


@dataclass
class DeviceLocator:
    device_id: str
    pf: ParticleFilter
    last_scan_ts: float | None = None
    last_estimate: Estimate | None = None
    manual_node: int | None = None
    manual_ts: float | None = None
    gps: GpsFix | None = None
    floor_confirmed_ts: float | None = None
    last_predict_ts: float | None = None
    history: list = field(default_factory=list)

    # ------------------------------------------------------------------ inputs

    def on_scan(
        self,
        readings: dict[str, float],
        ts: float,
        model: fp.FingerprintModel | None,
        uncertainty_db: float,
    ) -> Estimate | None:
        graph = self.pf.map.graph
        if self.last_predict_ts is not None:
            self.pf.predict(ts - self.last_predict_ts)
        self.last_predict_ts = ts
        observations = match_observations(readings, graph.access_points)
        probs = model.predict_proba(readings) if model else None
        if not self.pf.update(observations, probs, uncertainty_db):
            return self.last_estimate
        self.last_scan_ts = ts
        self.last_estimate = self.pf.estimate()
        return self.last_estimate

    def on_manual(self, node_id: int, ts: float) -> None:
        self.manual_node = node_id
        self.manual_ts = ts
        self.floor_confirmed_ts = ts
        self.pf.reseed_at_node(node_id)
        self.last_predict_ts = ts
        self.last_estimate = self.pf.estimate()

    def on_floor_confirm(self, level: int, ts: float) -> None:
        self.floor_confirmed_ts = ts
        graph = self.pf.map.graph
        if self.last_estimate and self.last_estimate.level != level:
            node = graph.nearest_node(self.last_estimate.x, self.last_estimate.y, level)
            if node is not None:
                self.pf.reseed_at_node(node, spread_m=6.0)
                self.last_estimate = self.pf.estimate()

    def on_gps(self, lat: float, lng: float, accuracy_m: float, ts: float) -> None:
        self.gps = GpsFix(lat, lng, accuracy_m, ts)

    # ------------------------------------------------------------------ output

    def fix(self, now: float, footprint: list | None, settings: dict) -> dict:
        graph = self.pf.map.graph
        low_conf = float(settings.get("low_confidence", 0.35))
        floor_conf_threshold = float(settings.get("floor_confirm_confidence", 0.6))
        wifi_fresh = self.last_scan_ts is not None and now - self.last_scan_ts <= WIFI_STALE_S
        manual_active = self.manual_ts is not None and now - self.manual_ts <= MANUAL_HOLD_S

        gps_info = None
        outside = False
        near_assembly = None
        if self.gps and now - self.gps.ts <= 60:
            gps_info = {"lat": self.gps.lat, "lng": self.gps.lng, "accuracy_m": self.gps.accuracy_m}
            if footprint and len(footprint) >= 3:
                inside = point_in_polygon(self.gps.lat, self.gps.lng, footprint)
                # only trust "outside" when the accuracy circle is clear of the footprint edge
                outside = not inside and distance_to_polygon_m(self.gps.lat, self.gps.lng, footprint) > self.gps.accuracy_m * 0.5
            for n in graph.nodes.values():
                if n.type == "assembly" and n.lat is not None and n.lng is not None:
                    if haversine_m(self.gps.lat, self.gps.lng, n.lat, n.lng) <= max(ASSEMBLY_RADIUS_M, self.gps.accuracy_m):
                        near_assembly = n.id
                        break

        est = self.last_estimate
        if manual_active and self.manual_node is not None:
            node = graph.nodes[self.manual_node]
            source, x, y, level, node_id, confidence = "manual", node.x, node.y, node.level, node.id, 0.9
            floor_confidence, spread = 1.0, 2.0
        elif est is not None and wifi_fresh:
            source, x, y, level, node_id = "wifi_pf", est.x, est.y, est.level, est.node_id
            confidence, floor_confidence, spread = est.confidence, est.floor_confidence, est.spread_m
        elif est is not None:
            # stale: keep last known position but flag it
            source, x, y, level, node_id = "last_known", est.x, est.y, est.level, est.node_id
            confidence, floor_confidence, spread = est.confidence * 0.5, est.floor_confidence, est.spread_m
        else:
            source, x, y, level, node_id, confidence, floor_confidence, spread = "unknown", None, None, None, None, 0.0, 0.0, None

        if outside and source != "manual":
            source = "gps"

        needs_picker = source in {"unknown", "last_known"} or (source == "wifi_pf" and confidence < low_conf)
        confirm_floor = (
            source == "wifi_pf"
            and floor_confidence < floor_conf_threshold
            and (self.floor_confirmed_ts is None or now - self.floor_confirmed_ts > FLOOR_CONFIRM_COOLDOWN_S)
        )
        return {
            "source": source,
            "x": None if x is None else round(x, 2),
            "y": None if y is None else round(y, 2),
            "level": level,
            "node_id": node_id,
            "confidence": round(confidence, 3),
            "floor_confidence": round(floor_confidence, 3),
            "spread_m": spread,
            "outside": outside,
            "near_assembly_node": near_assembly,
            "needs_picker": needs_picker and not outside,
            "confirm_floor": confirm_floor,
            "gps": gps_info,
        }


def new_locator(
    device_id: str, pf_map: PFMap, n_particles: int, seed: int | None = None, floor_attenuation_db: float = 15.0
) -> DeviceLocator:
    import numpy as np

    return DeviceLocator(device_id, ParticleFilter(pf_map, n_particles, np.random.default_rng(seed), floor_attenuation_db))


# ---------------------------------------------------------------------- geo helpers


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    inside = False
    n = len(polygon)
    for i in range(n):
        y1, x1 = polygon[i]
        y2, x2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lng < x_cross:
                inside = not inside
    return inside


def distance_to_polygon_m(lat: float, lng: float, polygon: list) -> float:
    """Approximate distance (m) from a point to the polygon boundary (equirectangular)."""
    k_lat = 111320.0
    k_lng = 111320.0 * math.cos(math.radians(lat))
    px, py = lng * k_lng, lat * k_lat
    best = math.inf
    n = len(polygon)
    for i in range(n):
        (la1, ln1), (la2, ln2) = polygon[i], polygon[(i + 1) % n]
        ax, ay, bx, by = ln1 * k_lng, la1 * k_lat, ln2 * k_lng, la2 * k_lat
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best
