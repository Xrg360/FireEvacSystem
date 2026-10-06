import json
from pathlib import Path

import pytest

from app.routing.graph import BuildingGraph

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"


@pytest.fixture(scope="session")
def villa() -> BuildingGraph:
    return BuildingGraph.from_dict(json.loads((FIXTURES / "block_a_villa.json").read_text()))


@pytest.fixture(scope="session")
def tower() -> BuildingGraph:
    return BuildingGraph.from_dict(json.loads((FIXTURES / "block_b_tower.json").read_text()))


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    """Fresh seeded SQLite database + Flask app (engine not started; tests tick it by hand)."""
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("ENGINE_INPROCESS", "0")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256-ok")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    from scripts.seed import seed

    seeded = seed(reset=True)
    from app import create_app
    from app.config import Config
    from app.live import store as store_mod

    store_mod._store = None
    cfg = Config()
    cfg.testing = True
    app = create_app(cfg, start_engine=False)
    from app.engine.engine import Engine
    from app.live.store import get_store

    engine = Engine(cfg, get_store())
    yield app, engine, seeded


def login(client, email, device=False, password="Evacuate@123"):
    body = {"email": email, "password": password}
    if device:
        body["device"] = {"platform": "android", "model": "pytest"}
    r = client.post("/api/auth/login", json=body)
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data
