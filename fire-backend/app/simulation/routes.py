"""Simulation console (dashboard) and the Table I benchmark."""

from __future__ import annotations

import threading
import uuid

from apiflask import APIBlueprint, abort
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.security import current_user, staff_required
from app.buildings.service import get_building_or_404, load_graph
from app.db import SessionLocal
from app.live.store import get_store
from app.models import BuildingMode, Node

bp = APIBlueprint("simulation", __name__, tag="simulation")

ACTIONS = {"start", "spawn", "ignite", "extinguish", "pause", "resume", "speed", "spread", "alarm", "reset", "stop"}


class SimIn(BaseModel):
    action: str
    occupants: int | None = Field(default=None, ge=0, le=1000)
    phone_share: float | None = Field(default=None, ge=0, le=1)
    mobility_share: float | None = Field(default=None, ge=0, le=1)
    node_id: int | None = None
    speed: float | None = Field(default=None, ge=0.25, le=10)
    spread_per_min: float | None = Field(default=None, ge=0, le=10)
    seed: int | None = None


class BenchmarkIn(BaseModel):
    seeds: int = Field(default=5, ge=1, le=30)
    occupants: int | None = Field(default=None, ge=1, le=600)
    fire_node_ids: list[int] = Field(default_factory=list)
    spread_per_min: float | None = Field(default=None, ge=0, le=10)
    use_predictor: bool = False


@bp.post("/buildings/<int:building_id>/simulation")
@staff_required
@bp.input(SimIn)
@bp.doc(summary="Control the simulator: start, spawn, ignite, extinguish, pause, resume, speed, spread, alarm, reset, stop")
def control(building_id: int, json_data: SimIn):
    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    if json_data.action not in ACTIONS:
        abort(422, f"Unknown action; use one of {sorted(ACTIONS)}")
    if b.mode != BuildingMode.SIMULATION:
        abort(409, "Switch the building to Simulation mode first")
    if json_data.action in {"ignite", "extinguish"}:
        node = SessionLocal.get(Node, json_data.node_id or 0)
        if node is None or node.building_id != b.id:
            abort(422, "node_id is required and must be in this building")
    msg = {"type": "sim", "building_id": b.id, **json_data.model_dump(exclude_none=True)}
    get_store().push_inbox(msg)
    return {"queued": True, "action": json_data.action}


_jobs: dict[str, dict] = {}


@bp.post("/buildings/<int:building_id>/benchmark")
@staff_required
@bp.input(BenchmarkIn)
@bp.doc(summary="Run static-plan vs dynamic-A* comparison (paper Table I) in the background")
def benchmark(building_id: int, json_data: BenchmarkIn):
    from app.simulation.benchmark import compare_graph

    b = get_building_or_404(SessionLocal, building_id, current_user().society_id)
    graph = load_graph(SessionLocal, b)
    fire_keys = []
    for nid in json_data.fire_node_ids:
        if nid not in graph.nodes:
            abort(422, f"Node {nid} not in building")
        fire_keys.append(graph.nodes[nid].key)
    if not fire_keys:
        rooms = SessionLocal.scalars(select(Node).where(Node.building_id == b.id, Node.type == "room")).all()
        if not rooms:
            abort(422, "Building has no rooms to start a fire in")
        fire_keys = [rooms[len(rooms) // 2].key]
    job = uuid.uuid4().hex[:12]
    _jobs[job] = {"status": "running", "building_id": b.id}

    def run():
        try:
            _jobs[job] = {"status": "done", "building_id": b.id, "result": compare_graph(
                graph, json_data.seeds, json_data.occupants or 60, fire_keys, 0.6 if json_data.spread_per_min is None else json_data.spread_per_min,
                json_data.use_predictor)}
        except Exception as exc:  # pragma: no cover
            _jobs[job] = {"status": "failed", "building_id": b.id, "error": str(exc)}

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job, "status": "running"}, 202


@bp.get("/benchmark/<job_id>")
@staff_required
def benchmark_result(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        abort(404, "Unknown job")
    return job
