"""Learned Wi-Fi fingerprinting.

Survey mode records labelled scans ({bssid: rssi} at a known node). A distance-weighted
k-nearest-neighbours classifier maps a new scan to a probability per node. Unlike
trilateration it needs no router positions, so it still works when residents' routers
haven't been mapped. Floor probability is the sum of node probabilities on that floor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier

MISSING_DBM = -100.0


@dataclass
class FingerprintModel:
    bssids: list[str]
    classifier: KNeighborsClassifier
    node_ids: list[int]
    n_samples: int

    def vectorize(self, readings: dict[str, float]) -> np.ndarray:
        lower = {k.lower(): v for k, v in readings.items()}
        return np.array([[float(lower.get(b, MISSING_DBM)) for b in self.bssids]])

    def predict_proba(self, readings: dict[str, float]) -> dict[int, float]:
        known = sum(1 for b in readings if b.lower() in set(self.bssids))
        if known == 0:
            return {}
        probs = self.classifier.predict_proba(self.vectorize(readings))[0]
        return {int(n): float(p) for n, p in zip(self.classifier.classes_, probs, strict=True) if p > 0}


def train(samples: list[tuple[int, dict[str, float]]], k: int = 5) -> FingerprintModel | None:
    labels = {node for node, _ in samples}
    if len(samples) < 4 or len(labels) < 2:
        return None
    bssids = sorted({b.lower() for _, readings in samples for b in readings})
    X = np.array([[float({k_.lower(): v for k_, v in r.items()}.get(b, MISSING_DBM)) for b in bssids] for _, r in samples])
    y = np.array([node for node, _ in samples])
    clf = KNeighborsClassifier(n_neighbors=min(k, len(samples)), weights="distance")
    clf.fit(X, y)
    return FingerprintModel(bssids, clf, sorted(labels), len(samples))


def cross_validate(samples: list[tuple[int, dict[str, float]]], node_xy: dict[int, tuple[float, float, int]], k: int = 5) -> dict:
    """Held-out accuracy and mean position error (metres) for the evaluation report."""
    labels = [n for n, _ in samples]
    counts = {n: labels.count(n) for n in set(labels)}
    folds = min(5, min(counts.values())) if counts else 0
    if folds < 2 or len(counts) < 2:
        return {"accuracy": None, "mean_error_m": None, "samples": len(samples), "folds": folds}
    bssids = sorted({b.lower() for _, r in samples for b in r})
    X = np.array([[float({k_.lower(): v for k_, v in r.items()}.get(b, MISSING_DBM)) for b in bssids] for _, r in samples])
    y = np.array(labels)
    clf = KNeighborsClassifier(n_neighbors=min(k, len(samples) - len(samples) // folds), weights="distance")
    pred = cross_val_predict(clf, X, y, cv=StratifiedKFold(n_splits=folds, shuffle=True, random_state=7))
    errors = []
    for truth, guess in zip(y, pred, strict=True):
        tx, ty, tl = node_xy[int(truth)]
        gx, gy, gl = node_xy[int(guess)]
        errors.append(float(np.hypot(tx - gx, ty - gy)) + 3.0 * abs(tl - gl))
    return {
        "accuracy": float(np.mean(pred == y)),
        "mean_error_m": float(np.mean(errors)),
        "samples": len(samples),
        "folds": folds,
    }
