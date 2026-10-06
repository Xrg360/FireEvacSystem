"""RSSI-based distance estimation (paper §III-B eq. 1 and §V-A eq. 3-5).

    d_est = d_ref * 10 ^ ( -(P_received - P_ref) / (10 * eta) )
    d_min = d_ref * 10 ^ ( -(P_received - P_ref + u) / (10 * eta) )
    d_max = d_ref * 10 ^ ( -(P_received - P_ref - u) / (10 * eta) )
"""

from __future__ import annotations

import math

import numpy as np

D_REF = 1.0


def estimate_distance(p_received: float, p_ref: float, eta: float, d_ref: float = D_REF) -> float:
    return d_ref * 10 ** (-(p_received - p_ref) / (10.0 * eta))


def distance_bounds(p_received: float, p_ref: float, eta: float, uncertainty_db: float, d_ref: float = D_REF) -> tuple[float, float]:
    d_min = d_ref * 10 ** (-(p_received - p_ref + uncertainty_db) / (10.0 * eta))
    d_max = d_ref * 10 ** (-(p_received - p_ref - uncertainty_db) / (10.0 * eta))
    return d_min, d_max


def expected_rssi(distance_m: float, p_ref: float, eta: float, d_ref: float = D_REF) -> float:
    """Inverse of eq. 1: the log-distance path loss model. Used by calibration and the simulator."""
    d = max(distance_m, 0.1)
    return p_ref - 10.0 * eta * math.log10(d / d_ref)


def fit_path_loss(distances_m: list[float], rssi_dbm: list[float]) -> tuple[float, float] | None:
    """Least-squares fit of P_ref and eta for one access point from surveyed samples.

    rssi = P_ref - 10*eta*log10(d)  is linear in log10(d). Needs >= 3 samples spanning
    at least a 1.5x range of distances; eta is clamped to a physically sensible 1.5-5.
    """
    if len(distances_m) < 3:
        return None
    d = np.clip(np.asarray(distances_m, dtype=float), 0.3, None)
    r = np.asarray(rssi_dbm, dtype=float)
    if d.max() / d.min() < 1.5:
        return None
    x = np.log10(d)
    A = np.vstack([np.ones_like(x), -10.0 * x]).T
    (p_ref, eta), *_ = np.linalg.lstsq(A, r, rcond=None)
    eta = float(np.clip(eta, 1.5, 5.0))
    # re-fit intercept with the clamped slope
    p_ref = float(np.mean(r + 10.0 * eta * x))
    return p_ref, eta
