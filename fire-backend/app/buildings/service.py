"""Building graph persistence: DB rows <-> BuildingGraph / fixture-format dict."""

from __future__ import annotations

from apiflask import abort
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessPoint, Building, Edge, EdgeKind, Floor, Node, NodeType
from app.routing.graph import BuildingGraph, validate_graph


def graph_dict(session: Session, building: Building) -> dict:
    floors = session.scalars(select(Floor).where(Floor.building_id == building.id).order_by(Floor.level)).all()
    nodes = session.scalars(select(Node).where(Node.building_id == building.id)).all()
    edges = session.scalars(select(Edge).where(Edge.building_id == building.id)).all()
    aps = session.scalars(select(AccessPoint).where(AccessPoint.building_id == building.id)).all()
    return {
        "building": {
            "id": building.id,
            "name": building.name,
            "floor_height_m": building.floor_height_m,
            "graph_version": building.graph_version,
            "footprint": building.footprint,
        },
        "floors": [
            {
                "id": f.id, "level": f.level, "name": f.name, "width_m": f.width_m, "height_m": f.height_m,
                "plan_image": f.plan_image, "scale_px_per_m": f.scale_px_per_m,
            }
            for f in floors
        ],
        "nodes": [
            {
                "id": n.id, "key": n.key, "name": n.name, "type": n.type.value, "floor_id": n.floor_id, "x": n.x, "y": n.y,
                "capacity": n.capacity, "exit_flow_per_min": n.exit_flow_per_min, "lat": n.lat, "lng": n.lng,
            }
            for n in nodes
        ],
        "edges": [
            {"id": e.id, "a": e.a_id, "b": e.b_id, "kind": e.kind.value, "length_m": e.length_m, "width_m": e.width_m, "accessible": e.accessible}
            for e in edges
        ],
        "access_points": [
            {
                "id": a.id, "bssid": a.bssid, "ssid": a.ssid, "floor_id": a.floor_id, "x": a.x, "y": a.y,
                "p_ref": a.p_ref, "eta": a.eta, "calibrated": a.calibrated, "enabled": a.enabled,
            }
            for a in aps
        ],
    }


def load_graph(session: Session, building: Building) -> BuildingGraph:
    return BuildingGraph.from_dict(graph_dict(session, building))


def get_building_or_404(session: Session, building_id: int, society_id: int | None) -> Building:
    b = session.get(Building, building_id)
    if b is None or (society_id is not None and b.society_id != society_id):
        abort(404, "Building not found")
    return b


def replace_graph(session: Session, building: Building, data: dict) -> list[str]:
    """Publish an edited graph. Existing ids are kept (fingerprints, sensors and signage keep
    pointing at the same nodes); entries without an id or with a negative (client temp) id are
    created; anything missing is deleted. Returns validation problems (nothing saved if any)."""
    # --- validate on a provisional graph first
    temp = _provisional(data)
    problems = validate_graph(temp)
    if problems:
        return problems

    floor_map: dict[int, int] = {}
    existing_floors = {f.id: f for f in session.scalars(select(Floor).where(Floor.building_id == building.id))}
    keep_floor_ids = set()
    for f in data["floors"]:
        fid = f.get("id")
        row = existing_floors.get(fid) if fid and fid > 0 else None
        if row is None:
            row = Floor(building_id=building.id, level=f["level"], name=f.get("name") or f"Floor {f['level']}")
            session.add(row)
        row.level = f["level"]
        row.name = f.get("name") or row.name
        row.width_m = float(f.get("width_m") or row.width_m or 30)
        row.height_m = float(f.get("height_m") or row.height_m or 20)
        if "plan_image" in f:
            row.plan_image = f["plan_image"]
        if "scale_px_per_m" in f:
            row.scale_px_per_m = f["scale_px_per_m"]
        session.flush()
        floor_map[fid if fid is not None else id(f)] = row.id
        keep_floor_ids.add(row.id)

    node_map: dict[int, int] = {}
    existing_nodes = {n.id: n for n in session.scalars(select(Node).where(Node.building_id == building.id))}
    keep_node_ids = set()
    for n in data["nodes"]:
        nid = n.get("id")
        row = existing_nodes.get(nid) if nid and nid > 0 else None
        if row is None:
            row = Node(building_id=building.id)
            session.add(row)
        row.floor_id = floor_map[n["floor_id"]]
        row.key = n.get("key") or f"N{nid}"
        row.name = n.get("name") or row.key
        row.type = NodeType(n["type"])
        row.x, row.y = float(n["x"]), float(n["y"])
        row.capacity = int(n.get("capacity") or 10)
        row.exit_flow_per_min = n.get("exit_flow_per_min")
        row.lat, row.lng = n.get("lat"), n.get("lng")
        session.flush()
        node_map[nid] = row.id
        keep_node_ids.add(row.id)

    for e in session.scalars(select(Edge).where(Edge.building_id == building.id)):
        session.delete(e)
    session.flush()
    for e in data["edges"]:
        session.add(
            Edge(
                building_id=building.id, a_id=node_map[e["a"]], b_id=node_map[e["b"]], kind=EdgeKind(e.get("kind", "corridor")),
                length_m=e.get("length_m"), width_m=float(e.get("width_m") or 1.2), accessible=bool(e.get("accessible", True)),
            )
        )

    existing_aps = {a.bssid: a for a in session.scalars(select(AccessPoint).where(AccessPoint.building_id == building.id))}
    keep_bssids = set()
    for a in data.get("access_points", []):
        bssid = a["bssid"].lower()
        row = existing_aps.get(bssid)
        if row is None:
            row = AccessPoint(building_id=building.id, bssid=bssid)
            session.add(row)
        row.ssid = a.get("ssid")
        row.floor_id = floor_map[a["floor_id"]]
        row.x, row.y = float(a["x"]), float(a["y"])
        row.p_ref = float(a.get("p_ref", row.p_ref if row.p_ref is not None else -40.0))
        row.eta = float(a.get("eta", row.eta if row.eta is not None else 2.7))
        row.enabled = bool(a.get("enabled", True))
        keep_bssids.add(bssid)
    for bssid, row in existing_aps.items():
        if bssid not in keep_bssids:
            session.delete(row)

    for nid, row in existing_nodes.items():
        if nid not in keep_node_ids:
            session.delete(row)
    session.flush()
    for fid, row in existing_floors.items():
        if fid not in keep_floor_ids:
            session.delete(row)

    if "footprint" in data.get("building", {}):
        building.footprint = data["building"]["footprint"]
    if data.get("building", {}).get("floor_height_m"):
        building.floor_height_m = float(data["building"]["floor_height_m"])
    building.graph_version = (building.graph_version or 0) + 1
    return []


def _provisional(data: dict) -> BuildingGraph:
    # map arbitrary client ids to themselves; from_dict only needs internal consistency
    try:
        return BuildingGraph.from_dict(
            {
                "building": {"id": 0, "name": "draft", "floor_height_m": data.get("building", {}).get("floor_height_m", 3.0)},
                "floors": data["floors"],
                "nodes": data["nodes"],
                "edges": data["edges"],
                "access_points": data.get("access_points", []),
            }
        )
    except KeyError as exc:
        abort(422, f"Graph references unknown id: {exc}")
    except (TypeError, ValueError) as exc:
        abort(422, f"Malformed graph: {exc}")


def import_fixture(session: Session, building: Building, data: dict) -> dict[str, int]:
    """Seed helper: load a fixture file into an empty building. Returns node key -> id."""
    problems = replace_graph(session, building, {**data, "nodes": data["nodes"], "edges": data["edges"]})
    if problems:
        raise ValueError(problems)
    session.flush()
    return {n.key: n.id for n in session.scalars(select(Node).where(Node.building_id == building.id))}
