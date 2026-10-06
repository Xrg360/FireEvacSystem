"""Particle filter localization (paper §III-B and §V-B, Algorithm 1).

Particles live on the walkable graph (an edge index plus a fraction along it), so estimates
never land inside walls. Each update:

  predict  - every particle walks a random distance (0..1.4 m/s * dt) along the graph;
  weight   - likelihood of the Wi-Fi scan given the particle position, combining
               * trilateration: eq. 4/5 distance bounds per router with a known position;
               * fingerprinting: kNN probability of the particle's nearest node;
  normalise, resample (systematic, when the effective sample size drops);
  estimate - weighted mean of the particles on the most likely floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.positioning.trilateration import Observation
from app.routing.graph import BuildingGraph

MAX_SPEED_MS = 1.4
TRILAT_SIGMA_M = 1.5
FINGERPRINT_FLOOR = 0.05
RANDOM_INJECTION = 0.03
MAX_APS = 8
FLOOR_ATTENUATION_DB = 15.0


class PFMap:
    """Vectorised edge geometry for one graph version."""

    def __init__(self, graph: BuildingGraph) -> None:
        self.graph = graph
        edges = list(graph.edges)
        # isolated nodes get a zero-length self edge so particles can sit on them
        connected = {e.a for e in edges} | {e.b for e in edges}
        self.edge_a: list[int] = [e.a for e in edges]
        self.edge_b: list[int] = [e.b for e in edges]
        self.edge_kind: list[str] = [e.kind for e in edges]
        for nid in graph.nodes:
            if nid not in connected:
                self.edge_a.append(nid)
                self.edge_b.append(nid)
                self.edge_kind.append("self")
        fh = graph.floor_height
        n = graph.nodes
        self.ax = np.array([n[a].x for a in self.edge_a])
        self.ay = np.array([n[a].y for a in self.edge_a])
        self.az = np.array([n[a].level * fh for a in self.edge_a])
        self.bx = np.array([n[b].x for b in self.edge_b])
        self.by = np.array([n[b].y for b in self.edge_b])
        self.bz = np.array([n[b].level * fh for b in self.edge_b])
        self.length = np.maximum(np.sqrt((self.bx - self.ax) ** 2 + (self.by - self.ay) ** 2 + (self.bz - self.az) ** 2), 1e-6)
        self.edge_a_arr = np.array(self.edge_a)
        self.edge_b_arr = np.array(self.edge_b)
        self.incident: dict[int, list[int]] = {nid: [] for nid in graph.nodes}
        for i, (a, b) in enumerate(zip(self.edge_a, self.edge_b, strict=True)):
            self.incident[a].append(i)
            if b != a:
                self.incident[b].append(i)
        self.n_edges = len(self.edge_a)
        # sampling proportional to length gives a uniform spread over the walkable area
        w = np.where(self.length < 0.01, 1.0, self.length)
        self.edge_sampling = w / w.sum()


@dataclass
class Estimate:
    x: float
    y: float
    level: int
    node_id: int
    confidence: float
    floor_confidence: float
    spread_m: float


class ParticleFilter:
    def __init__(
        self,
        pf_map: PFMap,
        n_particles: int = 400,
        rng: np.random.Generator | None = None,
        floor_attenuation_db: float = FLOOR_ATTENUATION_DB,
    ) -> None:
        self.map = pf_map
        self.n = n_particles
        self.rng = rng or np.random.default_rng()
        self.floor_attenuation_db = floor_attenuation_db
        self.initialize_uniform()

    # 1: initialise particles randomly across the map
    def initialize_uniform(self) -> None:
        self.edge = self.rng.choice(self.map.n_edges, size=self.n, p=self.map.edge_sampling)
        self.t = self.rng.random(self.n)
        self.dir = self.rng.choice([-1.0, 1.0], size=self.n)
        self.w = np.full(self.n, 1.0 / self.n)

    def reseed_at_node(self, node_id: int, spread_m: float = 2.0) -> None:
        """Manual 'Where are you?' pick: a strong observation, so collapse onto that node."""
        incident = self.map.incident.get(node_id)
        if not incident:
            return
        self.edge = self.rng.choice(incident, size=self.n)
        at_a = self.map.edge_a_arr[self.edge] == node_id
        frac = np.clip(self.rng.random(self.n) * spread_m / self.map.length[self.edge], 0, 0.5)
        self.t = np.where(at_a, frac, 1.0 - frac)
        self.dir = self.rng.choice([-1.0, 1.0], size=self.n)
        self.w = np.full(self.n, 1.0 / self.n)

    # ------------------------------------------------------------------ geometry

    def positions(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        m, e, t = self.map, self.edge, self.t
        x = m.ax[e] + t * (m.bx[e] - m.ax[e])
        y = m.ay[e] + t * (m.by[e] - m.ay[e])
        z = m.az[e] + t * (m.bz[e] - m.az[e])
        return x, y, z

    def nearest_nodes(self) -> np.ndarray:
        return np.where(self.t < 0.5, self.map.edge_a_arr[self.edge], self.map.edge_b_arr[self.edge])

    # ------------------------------------------------------------------ predict

    def predict(self, dt: float) -> None:
        if dt <= 0:
            return
        dt = min(dt, 30.0)
        step = self.rng.random(self.n) * MAX_SPEED_MS * dt
        self.t = self.t + self.dir * step / self.map.length[self.edge]
        over = np.where((self.t > 1.0) | (self.t < 0.0))[0]
        for i in over:
            node = self.map.edge_b[self.edge[i]] if self.t[i] > 1.0 else self.map.edge_a[self.edge[i]]
            choices = self.map.incident[node]
            new_edge = choices[self.rng.integers(len(choices))]
            self.edge[i] = new_edge
            if self.map.edge_a[new_edge] == node:
                self.t[i], self.dir[i] = 0.0, 1.0
            else:
                self.t[i], self.dir[i] = 1.0, -1.0
        # a few random particles let the filter recover if the person was lost ("kidnapped")
        k = int(self.n * RANDOM_INJECTION)
        if k:
            idx = self.rng.choice(self.n, size=k, replace=False)
            self.edge[idx] = self.rng.choice(self.map.n_edges, size=k, p=self.map.edge_sampling)
            self.t[idx] = self.rng.random(k)

    # ------------------------------------------------------------------ update

    def update(
        self,
        observations: list[Observation],
        fingerprint: dict[int, float] | None,
        uncertainty_db: float = 6.0,
        fingerprint_weight: float = 1.0,
    ) -> bool:
        if not observations and not fingerprint:
            return False
        log_w = np.zeros(self.n)
        x, y, z = self.positions()
        fh = self.map.graph.floor_height
        particle_level = np.rint(z / fh)
        # 3: compute weight for each particle based on RSSI errors (eq. 4/5 bounds).
        # Signals crossing floor slabs lose ``floor_attenuation_db`` per floor, so for a particle
        # on another floor than the router the received power is compensated before eq. 4/5.
        for o in sorted(observations, key=lambda ob: ob.rssi, reverse=True)[:MAX_APS]:
            floors_between = np.abs(particle_level - o.ap.level)
            p_adj = o.rssi + self.floor_attenuation_db * floors_between
            d_min = 10 ** (-(p_adj - o.ap.p_ref + uncertainty_db) / (10.0 * o.ap.eta))
            d_max = 10 ** (-(p_adj - o.ap.p_ref - uncertainty_db) / (10.0 * o.ap.eta))
            d = np.sqrt((x - o.ap.x) ** 2 + (y - o.ap.y) ** 2 + (z - o.ap.level * fh) ** 2)
            err = np.maximum(0.0, np.maximum(d_min - d, d - d_max))
            log_w += -0.5 * (err / TRILAT_SIGMA_M) ** 2
        if fingerprint:
            nodes = self.nearest_nodes()
            p = np.array([fingerprint.get(int(n), 0.0) for n in nodes])
            log_w += fingerprint_weight * np.log(FINGERPRINT_FLOOR + p)
        log_w -= log_w.max()
        self.w = self.w * np.exp(log_w)
        # 4: normalise weights
        total = self.w.sum()
        if not np.isfinite(total) or total <= 0:
            self.initialize_uniform()
            return False
        self.w /= total
        # 5: resample particles based on weights
        if 1.0 / np.sum(self.w**2) < self.n / 2:
            self._systematic_resample()
        return True

    def _systematic_resample(self) -> None:
        positions = (self.rng.random() + np.arange(self.n)) / self.n
        idx = np.searchsorted(np.cumsum(self.w), positions)
        idx = np.minimum(idx, self.n - 1)
        self.edge, self.t, self.dir = self.edge[idx], self.t[idx], self.dir[idx]
        self.w = np.full(self.n, 1.0 / self.n)

    # ------------------------------------------------------------------ estimate

    # 7: return estimated user location as the mean of the best particles
    def estimate(self) -> Estimate:
        x, y, z = self.positions()
        fh = self.map.graph.floor_height
        levels = np.rint(z / fh).astype(int)
        level_weights: dict[int, float] = {}
        for lvl in np.unique(levels):
            level_weights[int(lvl)] = float(self.w[levels == lvl].sum())
        level = max(level_weights, key=level_weights.get)
        floor_conf = level_weights[level]
        mask = levels == level
        w = self.w[mask] / self.w[mask].sum()
        mx, my = float(np.sum(w * x[mask])), float(np.sum(w * y[mask]))
        spread = float(math.sqrt(np.sum(w * ((x[mask] - mx) ** 2 + (y[mask] - my) ** 2))))
        # node: weighted vote of particle nodes on that floor
        nodes = self.nearest_nodes()[mask]
        votes: dict[int, float] = {}
        for nid, wi in zip(nodes, w, strict=True):
            votes[int(nid)] = votes.get(int(nid), 0.0) + float(wi)
        node_id = max(votes, key=votes.get)
        confidence = floor_conf * math.exp(-spread / 6.0)
        return Estimate(mx, my, level, node_id, round(confidence, 3), round(floor_conf, 3), round(spread, 2))

    def cloud(self, max_points: int = 120) -> list[list[float]]:
        """Downsampled particles for the dashboard / dev panel: [x, y, level, weight]."""
        x, y, z = self.positions()
        idx = np.argsort(-self.w)[:max_points]
        fh = self.map.graph.floor_height
        return [[round(float(x[i]), 2), round(float(y[i]), 2), int(round(z[i] / fh)), round(float(self.w[i]), 5)] for i in idx]
