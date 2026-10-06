"""Paper eq. 1-5, Alg. 1 (particle filter), Alg. 3 (triangulation) and learned fingerprinting."""

import numpy as np
import pytest

from app.positioning import fingerprint as fp
from app.positioning.fallback import haversine_m, new_locator, point_in_polygon
from app.positioning.particle_filter import PFMap
from app.positioning.rssi import distance_bounds, estimate_distance, expected_rssi, fit_path_loss
from app.positioning.trilateration import match_observations, triangulate
from app.simulation.rssi_synth import synth_scan, synth_survey


def test_eq1_reference_point():
    assert estimate_distance(-40, -40, 2.7) == pytest.approx(1.0)
    # 10*eta dB weaker -> 10x farther
    assert estimate_distance(-67, -40, 2.7) == pytest.approx(10.0)


def test_eq4_eq5_bounds_contain_estimate():
    for p in range(-90, -30, 5):
        d = estimate_distance(p, -40, 2.7)
        lo, hi = distance_bounds(p, -40, 2.7, 6)
        assert lo < d < hi


def test_path_loss_inverse():
    for d in (0.5, 1, 3, 12):
        assert estimate_distance(expected_rssi(d, -42, 3.0), -42, 3.0) == pytest.approx(d)


def test_fit_path_loss_recovers_parameters():
    rng = np.random.default_rng(0)
    d = rng.uniform(1, 20, 60)
    r = [expected_rssi(x, -38.0, 3.1) + rng.normal(0, 1.0) for x in d]
    p_ref, eta = fit_path_loss(list(d), r)
    assert p_ref == pytest.approx(-38.0, abs=1.5)
    assert eta == pytest.approx(3.1, abs=0.2)


def test_triangulation_noiseless_is_close(villa):
    rng = np.random.default_rng(1)
    target = villa.node_by_key("A-DINING")
    obs = match_observations(synth_scan(villa, target.x, target.y, 0, rng), villa.access_points)
    res = triangulate(obs)
    assert res is not None and np.hypot(res.x - target.x, res.y - target.y) < 6.0


def test_particle_filter_converges(tower):
    rng = np.random.default_rng(2)
    model = fp.train(synth_survey(tower, 10, rng))
    pf_map = PFMap(tower)
    errs, floors = [], 0
    for i, key in enumerate(["B3-F02", "B1-C3", "B0-LOBBY", "B2-REFUGE", "B1-F04"]):
        n = tower.node_by_key(key)
        loc = new_locator(f"d{i}", pf_map, 400, seed=i)
        est = None
        for k in range(5):
            est = loc.on_scan(synth_scan(tower, n.x, n.y, n.level, rng), k * 3.0, model, 6.0)
        errs.append(np.hypot(est.x - n.x, est.y - n.y))
        floors += est.level == n.level
    assert floors == 5
    assert np.median(errs) < 3.0


def test_fingerprint_cross_validation(villa):
    rng = np.random.default_rng(3)
    samples = synth_survey(villa, 12, rng)
    node_xy = {nid: (n.x, n.y, n.level) for nid, n in villa.nodes.items()}
    cv = fp.cross_validate(samples, node_xy)
    assert cv["accuracy"] > 0.5 and cv["mean_error_m"] < 5


def test_manual_pick_overrides(villa):
    loc = new_locator("m", PFMap(villa), 200, seed=4)
    node = villa.node_by_key("A-BEDROOM").id
    loc.on_manual(node, 100.0)
    fix = loc.fix(110.0, None, {})
    assert fix["source"] == "manual" and fix["node_id"] == node and not fix["needs_picker"]
    fix = loc.fix(200.0, None, {})
    assert fix["source"] == "last_known" and fix["needs_picker"]


def test_unknown_position_requests_picker(villa):
    loc = new_locator("u", PFMap(villa), 200, seed=5)
    fix = loc.fix(0.0, None, {})
    assert fix["source"] == "unknown" and fix["needs_picker"]


def test_gps_outside_footprint(villa):
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).resolve().parent.parent / "contracts/fixtures/block_a_villa.json").read_text())
    fp_poly = data["building"]["footprint"]
    loc = new_locator("g", PFMap(villa), 200, seed=6)
    assembly = villa.node_by_key("A-ASSEMBLY")
    loc.on_gps(assembly.lat, assembly.lng, 8.0, 10.0)
    fix = loc.fix(12.0, fp_poly, {})
    assert fix["outside"] and fix["source"] == "gps" and fix["near_assembly_node"] == assembly.id
    centre = [sum(p[0] for p in fp_poly) / 4, sum(p[1] for p in fp_poly) / 4]
    assert point_in_polygon(centre[0], centre[1], fp_poly)
    assert haversine_m(0, 0, 0, 0.001) == pytest.approx(111.2, abs=0.5)
