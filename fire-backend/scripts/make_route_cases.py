"""Write contracts/fixtures/route_cases.json: expected server routes that the app's offline
A* (Dart) and any other client must reproduce exactly (contract parity tests).

Cases use the offline cost model: hazards (alpha=4) + lifts pruned + stairs rule, no congestion.

    python -m scripts.make_route_cases
"""

from __future__ import annotations

import json
from pathlib import Path

from app.routing.graph import BuildingGraph
from app.routing.planner import Person, RoutingContext, plan_route
from app.simulation.fire import hazards_from_fire

FIX = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"

CASES = [
    ("block_a_villa", "A-TOILET2", ["A-KITCHEN", "A-TOILET"], True),
    ("block_a_villa", "A-MASTER", [], True),
    ("block_a_villa", "A-LIVING", ["A-VERANDAH"], True),
    ("block_a_villa", "A-BEDROOM", ["A-DINING", "A-BALCONY2"], True),
    ("block_b_tower", "B3-F02", [], True),
    ("block_b_tower", "B3-F02", ["B2-SW"], True),
    ("block_b_tower", "B2-F04", [], False),
    ("block_b_tower", "B1-F05", ["B1-C3"], True),
    ("block_b_tower", "B0-LOBBY", ["B0-C2"], False),
    ("block_b_tower", "B3-LIFT", ["B1-F02"], True),
]


def main() -> None:
    out = []
    for fixture, start, fire, stairs_ok in CASES:
        g = BuildingGraph.from_dict(json.loads((FIX / f"{fixture}.json").read_text()))
        explicit = {g.node_by_key(k).id: "fire" for k in fire}
        hazards = hazards_from_fire(g, set(explicit))
        ctx = RoutingContext(hazards=hazards, alpha=4.0, beta=0.0, gamma=0.0, incident_active=True)
        plan = plan_route(g, g.node_by_key(start).id, ctx, Person(stairs_ok))
        out.append({
            "fixture": fixture,
            "start": start,
            "fire": fire,
            "stairs_ok": stairs_ok,
            "expected_path": [g.nodes[n].key for n in plan.path] if plan else None,
            "expected_cost": round(plan.cost, 6) if plan else None,
            "expected_goal_type": plan.goal_type if plan else None,
        })
    (FIX / "route_cases.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {len(out)} cases")


if __name__ == "__main__":
    main()
