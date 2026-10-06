"""End-to-end API + engine flows on a seeded SQLite database (engine ticked by hand)."""

import numpy as np

from app.live.store import get_store
from app.routing.graph import BuildingGraph
from app.simulation.rssi_synth import synth_scan
from tests.conftest import login


def _scan_payload(graph: BuildingGraph, key: str, seed=0):
    n = graph.node_by_key(key)
    readings = synth_scan(graph, n.x, n.y, n.level, np.random.default_rng(seed))
    return {"readings": [{"bssid": b, "rssi": r} for b, r in readings.items()]}


def test_auth_signup_and_approval(app_ctx):
    app, _engine, _ = app_ctx
    c = app.test_client()
    info = c.get("/api/join/MITS2025").get_json()
    tower = next(b for b in info["buildings"] if "Tower" in b["name"])
    r = c.post("/api/auth/register", json={"join_code": "mits2025", "name": "Test User", "email": "t@example.com",
                                           "password": "longpassword", "building_id": tower["id"], "flat": "B-201"})
    assert r.status_code == 201
    hdr, data = login(c, "t@example.com", device=True, password="longpassword")
    assert data["user"]["status"] == "pending"
    assert c.get("/api/buildings", headers=hdr).status_code == 403  # pending can't use the app yet
    admin, _ = login(c, "admin@example.com")
    pending = c.get("/api/residents?status=pending", headers=admin).get_json()["items"]
    uid = next(u["id"] for u in pending if u["email"] == "t@example.com")
    assert c.post(f"/api/residents/{uid}/approve", headers=admin).status_code == 200
    assert c.get("/api/buildings", headers=hdr).status_code == 200
    # residents cannot approve
    assert c.post(f"/api/residents/{uid}/approve", headers=hdr).status_code == 403


def test_tracking_rejected_without_incident(app_ctx):
    app, _engine, _ = app_ctx
    c = app.test_client()
    hdr, _ = login(c, "resident.b1@example.com", device=True)
    r = c.post("/api/positioning/scan", headers=hdr, json={"readings": [{"bssid": "b0:00:00:00:00:01", "rssi": -50}]})
    assert r.status_code == 409


def test_sensor_fire_to_route_to_metrics(app_ctx):
    app, engine, seeded = app_ctx
    c = app.test_client()
    admin, _ = login(c, "admin@example.com")
    buildings = c.get("/api/buildings", headers=admin).get_json()["items"]
    tower = next(b for b in buildings if "Tower" in b["name"])
    graph = BuildingGraph.from_dict(c.get(f"/api/buildings/{tower['id']}/graph", headers=admin).get_json())

    # sensor 8 = Flat 102 kitchen: a hot reading triggers fire + incident
    sensor = next(s for s in seeded["sensors"] if s["name"].startswith("Flat 102"))
    r = c.post(f"/api/sensors/{sensor['id']}/readings", headers={"X-Sensor-Key": "wrong"}, json={"temperature_c": 80})
    assert r.status_code == 401
    r = c.post(f"/api/sensors/{sensor['id']}/readings", headers={"X-Sensor-Key": sensor["api_key"]}, json={"smoke": 50, "temperature_c": 75})
    assert r.get_json()["fire"] is True
    inc = c.get(f"/api/buildings/{tower['id']}", headers=admin).get_json()["incident"]
    assert inc and inc["status"] == "evacuating"

    # resident on floor 3 acknowledges and scans
    res, rdata = login(c, "resident.b1@example.com", device=True)
    device_id = rdata["device_id"]
    assert c.get("/api/me/incident", headers=res).get_json()["incident"]["id"] == inc["id"]
    assert c.post("/api/me/acknowledge", headers=res).status_code == 200
    for k in range(4):
        assert c.post("/api/positioning/scan", headers=res, json=_scan_payload(graph, "B3-F02", k)).status_code == 200
        engine.tick(now=1000.0 + 3 * k)
    state = get_store().get_device(device_id)
    assert state["fix"]["level"] == 3
    route = state["route"]
    assert route is not None and route["goal_type"] == "exit"
    fire_node = graph.node_by_key("B1-F02").id
    assert fire_node not in route["path"]
    assert route["steps"][-1]["kind"] == "exit"

    # dashboard snapshot (paper Fig. 3 KPIs)
    rescuer, _ = login(c, "rescuer@example.com")
    snap = c.get(f"/api/buildings/{tower['id']}/live", headers=rescuer).get_json()
    assert snap["kpis"]["fire_alerts"] == 1 and snap["kpis"]["real_devices"] >= 1
    assert snap["hazards"][str(fire_node)] == "fire"

    # wheelchair user gets a refuge route + SOS appears for rescuers
    res2, r2 = login(c, "resident.b2@example.com", device=True)
    c.post("/api/positioning/manual", headers=res2, json={"node_id": graph.node_by_key("B2-F04").id})
    engine.tick(now=1020.0)
    assert get_store().get_device(r2["device_id"])["route"]["goal_type"] == "refuge"
    assert c.post("/api/sos", headers=res2, json={"kind": "help", "note": "wheelchair"}).status_code == 201
    engine.tick(now=1021.0)
    snap = c.get(f"/api/buildings/{tower['id']}/live", headers=rescuer).get_json()
    assert snap["kpis"]["needs_help"] >= 1 and snap["sos"]

    # first resident reaches safety, rescuer declares all clear -> metrics
    assert c.post("/api/me/status", headers=res, json={"status": "safe"}).get_json()["status"] == "safe"
    engine.tick(now=1030.0)
    r = c.post(f"/api/incidents/{inc['id']}/status", headers=rescuer, json={"status": "all_clear"})
    metrics = r.get_json()["metrics"]
    assert metrics["status_counts"]["safe"] == 1
    assert metrics["route_assignments"] >= 2
    events = c.get(f"/api/incidents/{inc['id']}/events?types=route.assigned", headers=rescuer).get_json()["items"]
    assert events
    csv = c.get(f"/api/incidents/{inc['id']}/export.csv", headers=rescuer)
    assert csv.status_code == 200 and b"route.assigned" in csv.data


def test_simulation_mode_spawns_and_burns(app_ctx):
    app, engine, _ = app_ctx
    c = app.test_client()
    admin, _ = login(c, "admin@example.com")
    villa = next(b for b in c.get("/api/buildings", headers=admin).get_json()["items"] if "Villa" in b["name"])
    graph = BuildingGraph.from_dict(c.get(f"/api/buildings/{villa['id']}/graph", headers=admin).get_json())
    assert c.post(f"/api/buildings/{villa['id']}/simulation", headers=admin, json={"action": "start", "occupants": 20}).status_code == 409
    c.patch(f"/api/buildings/{villa['id']}", headers=admin, json={"mode": "simulation"})
    engine.tick(now=2000.0)
    assert c.post(f"/api/buildings/{villa['id']}/simulation", headers=admin,
                  json={"action": "start", "occupants": 20, "seed": 1}).status_code == 200
    kitchen = graph.node_by_key("A-KITCHEN").id
    c.post(f"/api/buildings/{villa['id']}/simulation", headers=admin, json={"action": "ignite", "node_id": kitchen})
    t = 2001.0
    for _ in range(40):
        engine.tick(now=t)
        t += 1.0
    snap = c.get(f"/api/buildings/{villa['id']}/live", headers=admin).get_json()
    assert snap["incident"] is not None, "simulated fire should open a (simulation) incident"
    assert snap["sim"]["summary"]["evacuated"] > 0
    assert snap["hazards"][str(kitchen)] == "fire"
    # signage reacts
    signs = c.get(f"/api/buildings/{villa['id']}/signage", headers=admin).get_json()["items"]
    disp = c.get(f"/api/signage/display/{signs[0]['token']}").get_json()
    assert disp["state"]["incident"] is True and disp["state"]["exit"]


def test_graph_publish_validation(app_ctx):
    app, _engine, _ = app_ctx
    c = app.test_client()
    admin, _ = login(c, "admin@example.com")
    villa = next(b for b in c.get("/api/buildings", headers=admin).get_json()["items"] if "Villa" in b["name"])
    g = c.get(f"/api/buildings/{villa['id']}/graph", headers=admin).get_json()
    bad = {**g, "nodes": [n for n in g["nodes"] if n["type"] != "exit"]}
    bad["edges"] = [e for e in g["edges"] if e["a"] in {n["id"] for n in bad["nodes"]} and e["b"] in {n["id"] for n in bad["nodes"]}]
    r = c.put(f"/api/buildings/{villa['id']}/graph", headers=admin, json=bad)
    assert r.status_code == 422
    # add a new room with a temp id and connect it
    living = next(n for n in g["nodes"] if n["key"] == "A-LIVING")
    good = {**g, "nodes": g["nodes"] + [{"id": -1, "key": "A-STUDY", "name": "Study", "type": "room", "floor_id": living["floor_id"],
                                         "x": 16, "y": 1, "capacity": 3}],
            "edges": g["edges"] + [{"a": living["id"], "b": -1, "kind": "door"}]}
    r = c.put(f"/api/buildings/{villa['id']}/graph", headers=admin, json=good)
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert out["building"]["graph_version"] == g["building"]["graph_version"] + 1
    assert any(n["key"] == "A-STUDY" and n["id"] > 0 for n in out["nodes"])
    assert {n["id"] for n in g["nodes"]} <= {n["id"] for n in out["nodes"]}, "existing node ids must be preserved"


def test_survey_calibrate(app_ctx):
    app, _engine, _ = app_ctx
    c = app.test_client()
    sv, _ = login(c, "surveyor@example.com")
    tower = next(b for b in c.get("/api/buildings", headers=sv).get_json()["items"] if "Tower" in b["name"])
    graph = BuildingGraph.from_dict(c.get(f"/api/buildings/{tower['id']}/graph", headers=sv).get_json())
    for i, key in enumerate(["B1-C1", "B1-C2", "B1-C3", "B1-F01", "B1-F03", "B1-F05", "B1-SW", "B1-SE"]):
        for k in range(4):
            r = c.post(f"/api/buildings/{tower['id']}/survey", headers=sv, json={"node_id": graph.node_by_key(key).id, **_scan_payload(graph, key, i * 10 + k)})
            assert r.status_code == 200
    out = c.post(f"/api/buildings/{tower['id']}/survey/calibrate", headers=sv).get_json()
    assert any(ap["calibrated"] for ap in out["access_points"])
    assert out["fingerprint_cross_validation"]["accuracy"] is not None


def test_engine_payloads_match_event_contracts(app_ctx):
    """Real engine output must validate against app/realtime/schemas.py (exported contracts)."""
    from app.realtime import emitter
    from app.realtime.schemas import EVENTS

    app, engine, seeded = app_ctx
    captured: list[tuple[str, dict]] = []

    class Capture:
        def emit(self, event, data, to=None):
            captured.append((event, data))

    emitter.set_socketio(Capture())
    try:
        c = app.test_client()
        admin, _ = login(c, "admin@example.com")
        tower = next(b for b in c.get("/api/buildings", headers=admin).get_json()["items"] if "Tower" in b["name"])
        graph = BuildingGraph.from_dict(c.get(f"/api/buildings/{tower['id']}/graph", headers=admin).get_json())
        c.post(f"/api/buildings/{tower['id']}/incidents", headers=admin, json={"kind": "drill"})
        res, _ = login(c, "resident.b1@example.com", device=True)
        for k in range(3):
            c.post("/api/positioning/scan", headers=res, json=_scan_payload(graph, "B2-F03", k))
            engine.tick(now=3000.0 + 3 * k)
    finally:
        emitter.set_socketio(None)
    seen = set()
    for event, data in captured:
        model = EVENTS.get(event)
        if model:
            model.model_validate(data)
            seen.add(event)
    assert {"snapshot", "route.assigned", "position.fix", "incident.updated", "signage.update", "hazards"} <= seen
