"""Turn a node path into landmark-style, step-by-step guidance for the app and signage."""

from __future__ import annotations

import math

from app.routing.graph import BuildingGraph


def build_steps(graph: BuildingGraph, path: list[int]) -> list[dict]:
    if not path:
        return []
    steps: list[dict] = []
    nodes = [graph.nodes[n] for n in path]
    start = nodes[0]
    if len(nodes) == 1:
        text = "You are at the exit. Move away from the building to the assembly point." if start.type == "exit" else "Stay where you are."
        return [{"node_id": start.id, "kind": "arrive", "text": text, "distance_m": 0.0}]

    steps.append({"node_id": start.id, "kind": "start", "text": f"Leave {start.name}.", "distance_m": 0.0})
    i = 1
    while i < len(nodes):
        node, prev = nodes[i], nodes[i - 1]
        dist = graph.walk_length(prev.id, node.id)
        if node.level != prev.level:
            # collapse a whole stair run into one instruction
            j = i
            while j + 1 < len(nodes) and nodes[j + 1].level != nodes[j].level:
                dist += graph.walk_length(nodes[j].id, nodes[j + 1].id)
                j += 1
            target = nodes[j]
            direction = "down" if target.level < prev.level else "up"
            floor = graph.floor_by_level(target.level)
            via = prev.name if prev.type in {"stair", "lift"} else node.name
            steps.append(
                {
                    "node_id": target.id,
                    "kind": "stairs",
                    "text": f"Take {via} {direction} to {floor.name if floor else f'level {target.level}'}.",
                    "distance_m": round(dist, 1),
                }
            )
            i = j + 1
            continue
        if node.type == "exit":
            steps.append({"node_id": node.id, "kind": "exit", "text": f"Exit the building through {node.name}.", "distance_m": round(dist, 1)})
        elif node.type == "refuge":
            steps.append(
                {
                    "node_id": node.id,
                    "kind": "refuge",
                    "text": f"Go to the refuge area: {node.name}. Rescuers have been told where you are.",
                    "distance_m": round(dist, 1),
                }
            )
        elif node.type in {"stair", "lift"}:
            steps.append({"node_id": node.id, "kind": "go", "text": f"Go to {node.name}.", "distance_m": round(dist, 1)})
        else:
            steps.append({"node_id": node.id, "kind": "go", "text": f"Go through {node.name}.", "distance_m": round(dist, 1)})
        i += 1
    return _merge_short_corridor_steps(steps)


def _merge_short_corridor_steps(steps: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for s in steps:
        if merged and s["kind"] == "go" and merged[-1]["kind"] == "go" and merged[-1]["distance_m"] < 3:
            merged[-1] = {**s, "distance_m": round(merged[-1]["distance_m"] + s["distance_m"], 1)}
        else:
            merged.append(s)
    return merged


def bearing_deg(graph: BuildingGraph, a: int, b: int) -> float:
    """Direction from node a to node b on the floor plan (0 = up/north on the plan, clockwise)."""
    na, nb = graph.nodes[a], graph.nodes[b]
    # plan coordinates: x to the right, y downward (image convention)
    return (math.degrees(math.atan2(nb.x - na.x, -(nb.y - na.y))) + 360.0) % 360.0
