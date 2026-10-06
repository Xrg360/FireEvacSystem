"""In-memory building graph (paper §III-C: rooms/intersections are nodes, passageways are edges).

Built either from database rows or from the JSON fixture format in ``contracts/fixtures``,
so routing, positioning and the simulator never depend on the ORM.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GNode:
    id: int
    key: str
    name: str
    type: str
    floor_id: int
    level: int
    x: float
    y: float
    capacity: int = 10
    exit_flow_per_min: float | None = None
    lat: float | None = None
    lng: float | None = None


@dataclass(frozen=True)
class GEdge:
    id: int
    a: int
    b: int
    kind: str
    length: float
    width: float = 1.2
    accessible: bool = True

    def other(self, node_id: int) -> int:
        return self.b if node_id == self.a else self.a


@dataclass(frozen=True)
class GAccessPoint:
    bssid: str
    floor_id: int
    level: int
    x: float
    y: float
    p_ref: float = -40.0
    eta: float = 2.7
    ssid: str | None = None


@dataclass
class GFloor:
    id: int
    level: int
    name: str
    width_m: float = 30.0
    height_m: float = 20.0


@dataclass
class BuildingGraph:
    building_id: int
    name: str
    floor_height: float
    nodes: dict[int, GNode]
    edges: list[GEdge]
    floors: dict[int, GFloor]
    access_points: list[GAccessPoint] = field(default_factory=list)
    graph_version: int = 1
    adjacency: dict[int, list[GEdge]] = field(init=False)
    key_index: dict[str, int] = field(init=False)
    min_vertical_len: float = field(init=False)

    def __post_init__(self) -> None:
        self.adjacency = {nid: [] for nid in self.nodes}
        for e in self.edges:
            self.adjacency[e.a].append(e)
            self.adjacency[e.b].append(e)
        self.key_index = {n.key: n.id for n in self.nodes.values()}
        per_level = [
            e.length / abs(self.nodes[e.a].level - self.nodes[e.b].level)
            for e in self.edges
            if self.nodes[e.a].level != self.nodes[e.b].level
        ]
        self.min_vertical_len = min(per_level) if per_level else self.floor_height

    # ------------------------------------------------------------------ queries

    @property
    def exits(self) -> list[int]:
        return [n.id for n in self.nodes.values() if n.type == "exit"]

    @property
    def refuges(self) -> list[int]:
        return [n.id for n in self.nodes.values() if n.type == "refuge"]

    def node_by_key(self, key: str) -> GNode:
        return self.nodes[self.key_index[key]]

    def z(self, node: GNode) -> float:
        return node.level * self.floor_height

    def distance(self, a: int, b: int) -> float:
        na, nb = self.nodes[a], self.nodes[b]
        return math.dist((na.x, na.y, self.z(na)), (nb.x, nb.y, self.z(nb)))

    def xy_distance(self, a: int, b: int) -> float:
        na, nb = self.nodes[a], self.nodes[b]
        return math.hypot(na.x - nb.x, na.y - nb.y)

    def lower_bound(self, a: int, b: int) -> float:
        """Admissible lower bound on walking distance between two nodes.

        Every edge is at least as long as the straight line between its ends, so a path is at
        least as long as the horizontal displacement. Every floor change goes through a vertical
        edge of length >= ``min_vertical_len`` per level. The max of two lower bounds is a lower
        bound, which keeps A* optimal (paper eq. 2: f(n) = g(n) + h(n)).
        """
        na, nb = self.nodes[a], self.nodes[b]
        horizontal = math.hypot(na.x - nb.x, na.y - nb.y)
        vertical = abs(na.level - nb.level) * self.min_vertical_len
        return max(horizontal, vertical)

    def edge_between(self, a: int, b: int) -> GEdge | None:
        return next((e for e in self.adjacency[a] if e.other(a) == b), None)

    def walk_length(self, a: int, b: int) -> float:
        edge = self.edge_between(a, b)
        return edge.length if edge else self.distance(a, b)

    def nearest_node(self, x: float, y: float, level: int, types: set[str] | None = None) -> int | None:
        best, best_d = None, math.inf
        for n in self.nodes.values():
            if n.level != level or (types and n.type not in types):
                continue
            d = math.hypot(n.x - x, n.y - y)
            if d < best_d:
                best, best_d = n.id, d
        return best

    def floor_by_level(self, level: int) -> GFloor | None:
        for f in self.floors.values():
            if f.level == level:
                return f
        return None

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_dict(cls, data: dict) -> BuildingGraph:
        b = data["building"]
        floor_height = float(b.get("floor_height_m", 3.0))
        floors = {
            f["id"]: GFloor(f["id"], f["level"], f.get("name", f"Floor {f['level']}"), f.get("width_m", 30.0), f.get("height_m", 20.0))
            for f in data["floors"]
        }
        nodes = {}
        for n in data["nodes"]:
            nodes[n["id"]] = GNode(
                id=n["id"],
                key=n.get("key", str(n["id"])),
                name=n.get("name", n.get("key", str(n["id"]))),
                type=n["type"],
                floor_id=n["floor_id"],
                level=floors[n["floor_id"]].level,
                x=float(n["x"]),
                y=float(n["y"]),
                capacity=int(n.get("capacity") or 10),
                exit_flow_per_min=n.get("exit_flow_per_min"),
                lat=n.get("lat"),
                lng=n.get("lng"),
            )
        edges = []
        for i, e in enumerate(data["edges"]):
            a, b_ = nodes[e["a"]], nodes[e["b"]]
            straight = math.dist((a.x, a.y, a.level * floor_height), (b_.x, b_.y, b_.level * floor_height))
            length = max(float(e.get("length_m") or 0.0), straight, 0.1)
            edges.append(
                GEdge(e.get("id") or -(i + 1), e["a"], e["b"], e.get("kind", "corridor"), length, float(e.get("width_m", 1.2)), bool(e.get("accessible", True)))
            )
        aps = [
            GAccessPoint(
                bssid=ap["bssid"].lower(),
                floor_id=ap["floor_id"],
                level=floors[ap["floor_id"]].level,
                x=float(ap["x"]),
                y=float(ap["y"]),
                p_ref=float(ap.get("p_ref", -40.0)),
                eta=float(ap.get("eta", 2.7)),
                ssid=ap.get("ssid"),
            )
            for ap in data.get("access_points", [])
            if ap.get("enabled", True)
        ]
        return cls(
            building_id=b.get("id", 0),
            name=b.get("name", "Building"),
            floor_height=floor_height,
            nodes=nodes,
            edges=edges,
            floors=floors,
            access_points=aps,
            graph_version=b.get("graph_version", 1),
        )

    def to_dict(self) -> dict:
        return {
            "building": {
                "id": self.building_id,
                "name": self.name,
                "floor_height_m": self.floor_height,
                "graph_version": self.graph_version,
            },
            "floors": [
                {"id": f.id, "level": f.level, "name": f.name, "width_m": f.width_m, "height_m": f.height_m}
                for f in sorted(self.floors.values(), key=lambda f: f.level)
            ],
            "nodes": [
                {
                    "id": n.id, "key": n.key, "name": n.name, "type": n.type, "floor_id": n.floor_id,
                    "x": n.x, "y": n.y, "capacity": n.capacity, "exit_flow_per_min": n.exit_flow_per_min,
                    "lat": n.lat, "lng": n.lng,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {"id": e.id, "a": e.a, "b": e.b, "kind": e.kind, "length_m": round(e.length, 3), "width_m": e.width, "accessible": e.accessible}
                for e in self.edges
            ],
            "access_points": [
                {"bssid": ap.bssid, "ssid": ap.ssid, "floor_id": ap.floor_id, "x": ap.x, "y": ap.y, "p_ref": ap.p_ref, "eta": ap.eta}
                for ap in self.access_points
            ],
        }


def validate_graph(graph: BuildingGraph) -> list[str]:
    """Problems a building editor should fix before publishing."""
    problems: list[str] = []
    if not graph.exits:
        problems.append("Building has no exit nodes.")
    levels = sorted({f.level for f in graph.floors.values()})
    if len(levels) > 1:
        connected_levels: set[int] = set()
        for e in graph.edges:
            la, lb = graph.nodes[e.a].level, graph.nodes[e.b].level
            if la != lb:
                connected_levels.update((la, lb))
        for lvl in levels:
            if lvl not in connected_levels:
                problems.append(f"Floor level {lvl} has no stairs or lift connecting it to another floor.")
    # every node must reach an exit (ignoring hazards)
    exits = set(graph.exits)
    reached: set[int] = set()
    frontier = list(exits)
    while frontier:
        nid = frontier.pop()
        if nid in reached:
            continue
        reached.add(nid)
        frontier.extend(e.other(nid) for e in graph.adjacency[nid])
    for n in graph.nodes.values():
        if n.id not in reached:
            problems.append(f"Node '{n.name}' ({n.key}) cannot reach any exit.")
    return problems
