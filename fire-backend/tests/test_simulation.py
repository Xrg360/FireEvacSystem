from app.congestion.predict import CongestionPredictor
from app.simulation.benchmark import run_once
from app.simulation.fire import hazards_from_fire


def test_simulation_finishes_and_dynamic_reduces_queues(tower):
    static = run_once(tower, 0, 120, ["B1-F02"], 0.8, "static")
    dynamic = run_once(tower, 0, 120, ["B1-F02"], 0.8, "dynamic")
    for r in (static, dynamic):
        assert r["evacuated"] + r["trapped"] + r["in_refuge"] == 120
    assert dynamic["avg_exit_queue"] < static["avg_exit_queue"]
    assert dynamic["avg_evac_time_s"] <= static["avg_evac_time_s"]


def test_baseline_predictor_runs(tower):
    r = run_once(tower, 1, 60, ["B2-F03"], 0.8, "dynamic", CongestionPredictor())
    assert r["evacuated"] > 0


def test_smoke_surrounds_fire(villa):
    k = villa.node_by_key("A-KITCHEN").id
    hz = hazards_from_fire(villa, {k})
    assert hz[k] == "fire"
    assert hz[villa.node_by_key("A-DINING").id] == "smoke"
    assert hz[villa.node_by_key("A-LIVING").id] == "risk"
