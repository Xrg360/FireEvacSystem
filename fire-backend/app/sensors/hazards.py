"""Hazard state per node. Explicit hazards (sensor / manual / simulation) are stored; smoke and
risk around fire are derived when routing so they always follow the fire."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Building, HazardLevel, NodeHazard, utcnow
from app.routing.graph import BuildingGraph
from app.simulation.fire import hazards_from_fire

SEVERITY = {"none": 0, "risk": 1, "smoke": 2, "fire": 3}


def merge_hazards(*maps: dict[int, str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in maps:
        for nid, lvl in m.items():
            if SEVERITY.get(lvl, 0) > SEVERITY.get(out.get(nid, "none"), 0):
                out[nid] = lvl
    return out


def explicit_hazards(session: Session, building_id: int) -> dict[int, tuple[str, str]]:
    rows = session.scalars(select(NodeHazard).where(NodeHazard.building_id == building_id)).all()
    return {r.node_id: (r.level.value, r.source) for r in rows if r.level != HazardLevel.NONE}


def effective_hazards(graph: BuildingGraph, explicit: dict[int, str]) -> dict[int, str]:
    fire = {n for n, lvl in explicit.items() if lvl == "fire" and n in graph.nodes}
    return merge_hazards({n: lvl for n, lvl in explicit.items() if n in graph.nodes}, hazards_from_fire(graph, fire))


def set_hazard(session: Session, building: Building, node_id: int, level: str, source: str) -> bool:
    """Upsert a node hazard. Returns True when something changed (hazard_version bumped)."""
    row = session.get(NodeHazard, node_id)
    level_enum = HazardLevel(level)
    if level_enum == HazardLevel.NONE:
        if row is None:
            return False
        session.delete(row)
    elif row is None:
        session.add(NodeHazard(node_id=node_id, building_id=building.id, level=level_enum, source=source, updated_at=utcnow()))
    else:
        if row.level == level_enum and row.source == source:
            return False
        # a sensor or manual confirmation outranks a simulated hazard
        if row.source in {"sensor", "manual"} and source == "simulation":
            return False
        row.level, row.source, row.updated_at = level_enum, source, utcnow()
    building.hazard_version = (building.hazard_version or 0) + 1
    return True


def clear_hazards(session: Session, building: Building, source: str | None = None) -> int:
    q = select(NodeHazard).where(NodeHazard.building_id == building.id)
    if source:
        q = q.where(NodeHazard.source == source)
    rows = session.scalars(q).all()
    for r in rows:
        session.delete(r)
    if rows:
        building.hazard_version = (building.hazard_version or 0) + 1
    return len(rows)
