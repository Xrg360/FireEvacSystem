"""Generate the demo society fixtures in contracts/fixtures.

Block A reproduces the single-floor house used in the paper (Fig. 3/4: Entrance, Verandah,
Living Room, Kitchen, ... with exits Entrance, Balcony1, Balcony2).
Block B is a 4-storey residential tower with two stair cores, a lift, refuge areas on
upper floors and three ground-floor exits (multi-floor, level-aware routing).

Run:  python -m scripts.make_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"

# Muthoot Institute of Technology and Science area, Kerala (approximate, for demo only)
ORIGIN_LAT, ORIGIN_LNG = 9.96210, 76.41180
M_LAT = 1 / 111320.0


def m_lng(lat: float) -> float:
    import math

    return 1 / (111320.0 * math.cos(math.radians(lat)))


def geo(x: float, y: float, ox: float, oy: float) -> tuple[float, float]:
    """Plan metres -> lat/lng. Plan y grows downward (south)."""
    lat = ORIGIN_LAT - (oy + y) * M_LAT
    lng = ORIGIN_LNG + (ox + x) * m_lng(ORIGIN_LAT)
    return round(lat, 7), round(lng, 7)


def block_a() -> dict:
    ox, oy = 0.0, 0.0
    floors = [{"id": 1, "level": 0, "name": "Ground Floor", "width_m": 24, "height_m": 16}]
    raw = [
        # key, name, type, x, y, capacity, exit_flow
        ("A-ENTRANCE", "Entrance", "exit", 2, 2, 8, 60),
        ("A-VERANDAH", "Verandah", "corridor", 7, 2, 10, None),
        ("A-LIVING", "Living Room", "room", 13, 3, 12, None),
        ("A-STAIRHALL", "Stair Hall", "corridor", 19, 3, 6, None),
        ("A-TOILET2", "Toilet2", "room", 10, 5.5, 2, None),
        ("A-DINING", "Dining Space", "room", 13, 8, 10, None),
        ("A-KITCHEN", "Kitchen", "room", 19, 8, 4, None),
        ("A-MASTER", "Master Bedroom", "room", 7, 8, 4, None),
        ("A-TOILET", "Toilet", "room", 2, 8, 2, None),
        ("A-BALCONY1", "Balcony1", "exit", 22, 13, 4, 20),
        ("A-BEDROOM", "Bedroom", "room", 7, 13, 4, None),
        ("A-BALCONY2", "Balcony2", "exit", 2, 14, 4, 20),
        ("A-ASSEMBLY", "Front Gate Assembly Point", "assembly", -6, 2, 200, None),
    ]
    nodes = []
    for i, (key, name, typ, x, y, cap, flow) in enumerate(raw, start=1):
        lat, lng = geo(x, y, ox, oy)
        nodes.append(
            {"id": i, "key": key, "name": name, "type": typ, "floor_id": 1, "x": x, "y": y, "capacity": cap,
             "exit_flow_per_min": flow, "lat": lat if typ in {"assembly", "exit"} else None, "lng": lng if typ in {"assembly", "exit"} else None}
        )
    k = {n["key"]: n["id"] for n in nodes}
    pairs = [
        ("A-ENTRANCE", "A-VERANDAH", "door"),
        ("A-VERANDAH", "A-LIVING", "corridor"),
        ("A-VERANDAH", "A-MASTER", "corridor"),
        ("A-LIVING", "A-STAIRHALL", "corridor"),
        ("A-LIVING", "A-TOILET2", "door"),
        ("A-LIVING", "A-DINING", "corridor"),
        ("A-DINING", "A-KITCHEN", "door"),
        ("A-DINING", "A-MASTER", "door"),
        ("A-DINING", "A-BEDROOM", "door"),
        ("A-MASTER", "A-TOILET", "door"),
        ("A-KITCHEN", "A-BALCONY1", "door"),
        ("A-STAIRHALL", "A-KITCHEN", "door"),
        ("A-BEDROOM", "A-BALCONY2", "door"),
        ("A-ENTRANCE", "A-ASSEMBLY", "outdoor"),
    ]
    edges = [{"id": i, "a": k[a], "b": k[b], "kind": kind, "width_m": 1.0 if kind == "door" else 1.5, "accessible": True}
             for i, (a, b, kind) in enumerate(pairs, start=1)]
    aps = [
        {"bssid": "a0:00:00:00:00:01", "ssid": "BlockA-Hall", "floor_id": 1, "x": 5, "y": 4, "p_ref": -40.0, "eta": 2.7},
        {"bssid": "a0:00:00:00:00:02", "ssid": "BlockA-Kitchen", "floor_id": 1, "x": 18, "y": 5, "p_ref": -40.0, "eta": 2.7},
        {"bssid": "a0:00:00:00:00:03", "ssid": "BlockA-Bedrooms", "floor_id": 1, "x": 10, "y": 13, "p_ref": -40.0, "eta": 2.7},
        {"bssid": "a0:00:00:00:00:04", "ssid": "BlockA-Dining", "floor_id": 1, "x": 15, "y": 10, "p_ref": -42.0, "eta": 2.9},
    ]
    footprint = [list(geo(-1, -1, ox, oy)), list(geo(25, -1, ox, oy)), list(geo(25, 17, ox, oy)), list(geo(-1, 17, ox, oy))]
    return {
        "building": {"id": 1, "name": "Block A (Villa)", "floor_height_m": 3.0, "graph_version": 1, "footprint": footprint},
        "floors": floors,
        "nodes": nodes,
        "edges": edges,
        "access_points": aps,
        "sensors": [
            {"name": "Kitchen smoke detector", "type": "multi", "node_key": "A-KITCHEN"},
            {"name": "Living room smoke detector", "type": "multi", "node_key": "A-LIVING"},
            {"name": "Master bedroom smoke detector", "type": "multi", "node_key": "A-MASTER"},
        ],
        "signage": [{"name": "Verandah display", "node_key": "A-VERANDAH"}, {"name": "Dining display", "node_key": "A-DINING"}],
    }


def block_b(levels: int = 4) -> dict:
    ox, oy = 40.0, 0.0
    floors = []
    nodes = []
    edges = []
    aps = []
    nid = 100
    eid = 100

    def add_node(key, name, typ, floor_id, x, y, cap, flow=None, with_geo=False):
        nonlocal nid
        nid += 1
        lat = lng = None
        if with_geo:
            lat, lng = geo(x, y, ox, oy)
        nodes.append({"id": nid, "key": key, "name": name, "type": typ, "floor_id": floor_id, "x": x, "y": y,
                      "capacity": cap, "exit_flow_per_min": flow, "lat": lat, "lng": lng})
        return nid

    def add_edge(a, b, kind, length=None, width=1.5, accessible=True):
        nonlocal eid
        eid += 1
        e = {"id": eid, "a": a, "b": b, "kind": kind, "width_m": width, "accessible": accessible}
        if length:
            e["length_m"] = length
        edges.append(e)

    stair_w, stair_e, lift = {}, {}, {}
    for lvl in range(levels):
        fid = 10 + lvl
        fname = "Ground Floor" if lvl == 0 else f"Floor {lvl}"
        floors.append({"id": fid, "level": lvl, "name": fname, "width_m": 30, "height_m": 16})
        p = f"B{lvl}"
        c1 = add_node(f"{p}-C1", f"{fname} West Corridor", "corridor", fid, 6, 8, 15)
        c2 = add_node(f"{p}-C2", f"{fname} Central Corridor", "corridor", fid, 15, 8, 15)
        c3 = add_node(f"{p}-C3", f"{fname} East Corridor", "corridor", fid, 24, 8, 15)
        add_edge(c1, c2, "corridor")
        add_edge(c2, c3, "corridor")
        sw = add_node(f"{p}-SW", "West Staircase", "stair", fid, 2, 8, 12)
        se = add_node(f"{p}-SE", "East Staircase", "stair", fid, 28, 8, 12)
        lf = add_node(f"{p}-LIFT", "Lift Lobby", "lift", fid, 15, 11, 8)
        add_edge(c1, sw, "door", width=1.2)
        add_edge(c3, se, "door", width=1.2)
        add_edge(c2, lf, "corridor")
        stair_w[lvl], stair_e[lvl], lift[lvl] = sw, se, lf
        if lvl == 0:
            for name, x, y, corridor in (("Lobby", 15, 3, c2), ("Clubhouse", 24, 13, c3), ("Security Cabin", 6, 13, c1)):
                r = add_node(f"{p}-{name.upper().replace(' ', '')}", name, "room", fid, x, y, 20 if name != "Security Cabin" else 3)
                add_edge(corridor, r, "door")
            main = add_node(f"{p}-EXIT-MAIN", "Main Entrance", "exit", fid, 15, 15.5, 10, 60, with_geo=True)
            west = add_node(f"{p}-EXIT-WEST", "West Fire Exit", "exit", fid, 0, 8, 6, 40, with_geo=True)
            east = add_node(f"{p}-EXIT-EAST", "East Fire Exit", "exit", fid, 30, 8, 6, 40, with_geo=True)
            add_edge(lf, main, "corridor", width=2.5)
            add_edge(sw, west, "door", width=1.2)
            add_edge(se, east, "door", width=1.2)
            assembly = add_node(f"{p}-ASSEMBLY", "Parking Assembly Point", "assembly", fid, 15, 24, 300, with_geo=True)
            add_edge(main, assembly, "outdoor", width=4)
        else:
            flats = [("01", 6, 3, c1), ("02", 15, 3, c2), ("03", 24, 3, c3), ("04", 6, 13, c1), ("05", 24, 13, c3)]
            for num, x, y, corridor in flats:
                f = add_node(f"{p}-F{num}", f"Flat {lvl}{num}", "room", fid, x, y, 6)
                add_edge(corridor, f, "door", width=1.0)
            refuge = add_node(f"{p}-REFUGE", f"{fname} Refuge Area", "refuge", fid, 28, 13, 10)
            add_edge(se, refuge, "door", width=1.5)
        aps.append({"bssid": f"b0:00:00:00:0{lvl}:01", "ssid": f"BlockB-{lvl}-W", "floor_id": fid, "x": 8, "y": 6, "p_ref": -40.0, "eta": 2.8})
        aps.append({"bssid": f"b0:00:00:00:0{lvl}:02", "ssid": f"BlockB-{lvl}-E", "floor_id": fid, "x": 22, "y": 10, "p_ref": -40.0, "eta": 2.8})
        aps.append({"bssid": f"b0:00:00:00:0{lvl}:03", "ssid": f"BlockB-{lvl}-C", "floor_id": fid, "x": 15, "y": 4, "p_ref": -41.0, "eta": 2.8})
    for lvl in range(levels - 1):
        add_edge(stair_w[lvl], stair_w[lvl + 1], "stair", length=8.0, width=1.2, accessible=False)
        add_edge(stair_e[lvl], stair_e[lvl + 1], "stair", length=8.0, width=1.2, accessible=False)
        add_edge(lift[lvl], lift[lvl + 1], "lift", length=3.0, width=1.5)

    footprint = [list(geo(-1, -1, ox, oy)), list(geo(31, -1, ox, oy)), list(geo(31, 17, ox, oy)), list(geo(-1, 17, ox, oy))]
    sensors = []
    for lvl in range(levels):
        sensors.append({"name": f"Floor {lvl} corridor detector", "type": "multi", "node_key": f"B{lvl}-C2"})
    sensors.append({"name": "Flat 102 kitchen detector", "type": "multi", "node_key": "B1-F02"})
    sensors.append({"name": "Fire alarm panel relay", "type": "alarm_panel", "node_key": "B0-LOBBY"})
    signage = [{"name": f"Floor {lvl} lift lobby display", "node_key": f"B{lvl}-LIFT"} for lvl in range(levels)]
    return {
        "building": {"id": 2, "name": "Block B (Tower)", "floor_height_m": 3.2, "graph_version": 1, "footprint": footprint},
        "floors": floors,
        "nodes": nodes,
        "edges": edges,
        "access_points": aps,
        "sensors": sensors,
        "signage": signage,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("block_a_villa.json", block_a()), ("block_b_tower.json", block_b())):
        (OUT / name).write_text(json.dumps(data, indent=2))
        print(f"wrote {OUT / name}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")


if __name__ == "__main__":
    main()
