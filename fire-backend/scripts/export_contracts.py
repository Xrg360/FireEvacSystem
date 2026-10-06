"""Write contracts/openapi.json and contracts/events.schema.json.

    python -m scripts.export_contracts

The dashboard generates TypeScript types from these (npm run gen:api).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "contracts"


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'contracts.db'}"
    os.environ["ENGINE_INPROCESS"] = "0"
    os.environ["REDIS_URL"] = ""
    from app import create_app
    from app.realtime.schemas import EVENTS

    app = create_app(start_engine=False)
    with app.app_context():
        spec = app.spec
    (OUT / "openapi.json").write_text(json.dumps(spec, indent=2))
    events = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Smart Fire Evacuation Socket.IO events (server -> client)",
        "events": {name: model.model_json_schema() for name, model in EVENTS.items()},
    }
    (OUT / "events.schema.json").write_text(json.dumps(events, indent=2))
    print(f"wrote {OUT / 'openapi.json'} ({len(spec.get('paths', {}))} paths) and events.schema.json ({len(EVENTS)} events)")


if __name__ == "__main__":
    main()
