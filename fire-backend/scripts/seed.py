"""Create the demo society: Block A (paper's villa) + Block B (4-storey tower), users, sensors, signage.

    python -m scripts.seed            # idempotent: skips if the society already exists
    python -m scripts.seed --reset    # drop everything first (SQLite / dev only)

Prints demo logins and sensor API keys (keys are only shown here, once).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.auth.security import hash_password, hash_secret, new_token
from app.buildings.service import import_fixture
from app.config import Config
from app.db import Base, get_engine, init_db, session_scope
from app.models import (
    DEFAULT_BUILDING_SETTINGS,
    Building,
    Role,
    Sensor,
    SensorType,
    Signage,
    Society,
    User,
    UserStatus,
)

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"
JOIN_CODE = "MITS2025"
PASSWORD = "Evacuate@123"

USERS = [
    ("admin@example.com", "Society Admin", Role.SOCIETY_ADMIN, None, None, True),
    ("rescuer@example.com", "Fire Officer Ravi", Role.RESCUER, None, None, True),
    ("surveyor@example.com", "Survey Engineer", Role.SURVEYOR, 2, None, True),
    ("resident.a@example.com", "Anitha (Villa)", Role.RESIDENT, 1, "Villa A", True),
    ("resident.b1@example.com", "Bhavan (B-302)", Role.RESIDENT, 2, "B-302", True),
    ("resident.b2@example.com", "Mary (B-105, wheelchair)", Role.RESIDENT, 2, "B-105", False),
]


def seed(reset: bool = False) -> dict:
    cfg = Config()
    init_db(cfg.database_url)
    from app import models  # noqa: F401

    if reset:
        Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    out: dict = {"sensors": [], "signage": [], "users": []}
    with session_scope() as s:
        if s.scalars(select(Society).where(Society.join_code == JOIN_CODE)).first():
            print("Demo society already exists; use --reset to recreate.")
            return out
        society = Society(name="MITS Green Meadows Residency", address="Varikoli, Puthencruz, Kerala", join_code=JOIN_CODE)
        s.add(society)
        s.flush()
        buildings: dict[int, Building] = {}
        node_keys: dict[int, dict[str, int]] = {}
        for idx, fixture in ((1, "block_a_villa.json"), (2, "block_b_tower.json")):
            data = json.loads((FIXTURES / fixture).read_text())
            b = Building(society_id=society.id, name=data["building"]["name"], floor_height_m=data["building"]["floor_height_m"],
                         footprint=data["building"]["footprint"], settings=dict(DEFAULT_BUILDING_SETTINGS))
            s.add(b)
            s.flush()
            keys = import_fixture(s, b, data)
            b.graph_version = 1
            buildings[idx], node_keys[idx] = b, keys
            for sensor in data.get("sensors", []):
                key = new_token(18)
                row = Sensor(building_id=b.id, node_id=keys[sensor["node_key"]], name=sensor["name"], type=SensorType(sensor["type"]),
                             api_key_hash=hash_secret(key))
                s.add(row)
                s.flush()
                out["sensors"].append({"building": b.name, "id": row.id, "name": row.name, "api_key": key})
            for sign in data.get("signage", []):
                row = Signage(building_id=b.id, node_id=keys[sign["node_key"]], name=sign["name"], token=new_token(12))
                s.add(row)
                s.flush()
                out["signage"].append({"building": b.name, "name": row.name, "token": row.token})
        for email, name, role, bidx, flat, stairs_ok in USERS:
            u = User(email=email, password_hash=hash_password(PASSWORD), name=name, role=role, status=UserStatus.APPROVED,
                     society_id=society.id, building_id=buildings[bidx].id if bidx else None, flat=flat, stairs_ok=stairs_ok,
                     phone="+91 90000 0000" + str(len(out["users"])),
                     mobility_notes=None if stairs_ok else "Wheelchair user - cannot use stairs")
            s.add(u)
            out["users"].append({"email": email, "role": role.value, "building": buildings[bidx].name if bidx else None})
        # a pending signup so the approval queue has something in it
        s.add(User(email="new.resident@example.com", password_hash=hash_password(PASSWORD), name="New Resident (pending)",
                   role=Role.RESIDENT, status=UserStatus.PENDING, society_id=society.id, building_id=buildings[2].id, flat="B-204"))
        out["society"] = {"name": society.name, "join_code": JOIN_CODE}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    out = seed(args.reset)
    if not out.get("society"):
        return
    print(f"\nSociety: {out['society']['name']}   join code: {out['society']['join_code']}")
    print(f"\nDemo logins (password for all: {PASSWORD})")
    for u in out["users"]:
        print(f"  {u['email']:<26} {u['role']:<14} {u['building'] or ''}")
    print("\nSensor API keys (shown once):")
    for sn in out["sensors"]:
        print(f"  #{sn['id']:<3} {sn['building']:<18} {sn['name']:<32} {sn['api_key']}")
    print("\nSignage display URLs (dashboard): /signage/<token>")
    for sg in out["signage"]:
        print(f"  {sg['building']:<18} {sg['name']:<28} /signage/{sg['token']}")


if __name__ == "__main__":
    main()
