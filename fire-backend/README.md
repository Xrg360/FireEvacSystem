# fire-backend

This is the Flask + Flask-SocketIO server for the **AI-Driven Smart Fire Evacuation System** (IEEE ICSCC 2025). It is the paper's "centralized processing server".

It does four jobs:
- turns residents' Wi-Fi scans into positions;
- plans a personal escape route for everyone;
- reacts to sensors and congestion every second;
- feeds the rescuer dashboard, the phones and the signage displays in real time.

It is part of the [FireEvacSystem monorepo](../README.md), alongside the [dashboard](../dashboard-final) and the [resident app](../MainProjectFlutter). Algorithms, the engine loop, the event contract and the data model are documented in [DEEP_DIVE.md](../DEEP_DIVE.md). Reproducible results are in [EVALUATION.md](EVALUATION.md).

> ⚠️ **Not a certified life-safety system.** It adds to, and does not replace, fire alarms, fire exits and trained responders.

<img src="../docs/screenshots/dashboard-benchmark.jpg" alt="Static plan vs dynamic A* benchmark run by this server" width="100%"/>

---

## What's inside

| Paper | Module |
|---|---|
| Eq. 1/3: RSSI to distance; eq. 4/5: distance bounds; P_ref/η calibration | `app/positioning/rssi.py` |
| Alg. 1: particle filter (graph-constrained, floor-slab compensation) | `app/positioning/particle_filter.py` |
| Alg. 3: weighted triangulation | `app/positioning/trilateration.py` |
| Learned Wi-Fi fingerprinting (kNN), an addition to the paper | `app/positioning/fingerprint.py` |
| Fallback chain: Wi-Fi, then manual pick, then GPS (outside/assembly), then last known | `app/positioning/fallback.py` |
| Alg. 2: A\* (eq. 2), multi-goal, admissible multi-floor heuristic | `app/routing/astar.py`, `app/routing/graph.py` |
| Cost model: hazard, congestion, exit wait; lifts excluded; refuge routing | `app/routing/planner.py` |
| Rerouting (hazard, deviation, congestion) with safeguards against flip-flopping | `app/engine/router.py` |
| Predictive congestion (Table II), an addition to the paper | `app/congestion/predict.py`, `scripts/train_congestion.py` |
| §IV system flow, run once per second | `app/engine/engine.py` |
| §VI WebSocket publish/subscribe | `app/realtime/` (Flask-SocketIO; Redis as the message queue in Docker) |
| §III-E digital signage | `app/signage/` |
| §IV-4 post-incident log, replay, metrics, CSV | `app/incidents/` |
| Fire sensors: HTTP and optional MQTT, alarm-panel relay | `app/sensors/` |
| §VII evaluation: static vs dynamic benchmark | `app/simulation/benchmark.py` |

---

## Run it

### Option A: local, no Docker

This uses SQLite, keeps live state in memory, and runs the engine as a thread inside the API process. The commands use the Windows paths (`.venv/Scripts/...`); on macOS or Linux use `.venv/bin/...`.

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```
2. Install the dependencies:
   ```bash
   .venv/Scripts/pip install -r requirements-dev.txt
   ```
3. Create the demo society. It prints logins, sensor API keys and signage links; the keys are shown only this once:
   ```bash
   .venv/Scripts/python -m scripts.seed
   ```
4. Start the API, Socket.IO and the engine on `0.0.0.0:5000`:
   ```bash
   .venv/Scripts/python run.py
   ```

- Interactive API docs: **http://localhost:5000/docs**.
- Health check: `GET /api/health`.
- To wipe everything and start fresh, run `.venv/Scripts/python -m scripts.seed --reset`. Signed-in apps will be asked to log in again.

### Option B: Docker Compose

This runs Postgres, Redis, a separate engine process and the dashboard.

1. Create `.env` from the template, then set `JWT_SECRET` (and `FIREBASE_CREDENTIALS` if you use push):
   ```bash
   cp .env.example .env
   ```
2. Build and start everything:
   ```bash
   docker compose up --build
   ```
3. Seed the demo society:
   ```bash
   docker compose exec api python -m scripts.seed
   ```
4. Optional: add the MQTT sensor broker and bridge:
   ```bash
   docker compose --profile mqtt up
   ```

The services are `db`, `redis`, `migrate` (Alembic, runs once), `api` (gunicorn: 1 worker, 100 threads), `engine` (`python -m app.engine`), `dashboard`, and optionally `mosquitto` and `mqtt-ingest`.

### Phones on the network

Phones must be on the **same Wi-Fi** as the server. In the app, enter `http://<server-LAN-IP>:5000`. Find the IP with `ipconfig` (Windows) or `ip a` (Linux).

On Windows, allow the port once, in PowerShell **as Administrator**:

```bash
New-NetFirewallRule -DisplayName "Fire Evac API" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
```

An Android emulator reaches the host machine at `http://10.0.2.2:5000`.

### Demo accounts

These are created by `scripts.seed`. The password for all of them is `Evacuate@123`, and the society join code is **`MITS2025`**.

| Email | Role |
|---|---|
| `admin@example.com` | Society admin: approvals, editor, settings |
| `rescuer@example.com` | Rescuer: live command view, SOS |
| `surveyor@example.com` | Surveyor: Wi-Fi survey mode in the app |
| `resident.b1@example.com` | Resident, Block B tower, flat B-302 |
| `resident.b2@example.com` | Resident, Block B, wheelchair user (routed to refuge areas) |
| `resident.a@example.com` | Resident, Block A villa |
| `new.resident@example.com` | Pending signup, to show the approval queue |

The demo society has two buildings:
- **Block A** is the paper's single-floor villa.
- **Block B** is a 4-storey tower with two staircases, a lift, refuge areas on each upper floor and three exits.

---

## Configuration

These are environment variables, set in `.env` or the shell.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///fire.db` | Postgres: `postgresql+psycopg://user:pass@host:5432/db` |
| `REDIS_URL` | empty | Empty means in-memory live state (a single process only). Required when the engine runs separately. |
| `ENGINE_INPROCESS` | `1` | Run the engine inside the API process |
| `JWT_SECRET` | dev value | **Change for any real deployment** |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | 60 / 30 | Token lifetimes. Refresh tokens rotate on use. |
| `CORS_ORIGINS` | `http://localhost:3000` | Dashboard origins allowed for REST and Socket.IO |
| `FIREBASE_CREDENTIALS` | empty | Path to the Firebase service-account JSON; enables push |
| `MQTT_HOST` / `MQTT_PORT` | empty / 1883 | Optional sensor broker |
| `POSITION_RETENTION_DAYS` | 7 | How long resident position history is kept |
| `ENGINE_TICK_SECONDS` | 1.0 | Engine loop period |
| `UPLOAD_DIR` / `MODEL_DIR` | `uploads/`, `ml_models/` | Floor-plan images; trained congestion model |

Per-building routing, positioning and detection settings (α/β/γ, congestion threshold, reroute safeguards, RSSI uncertainty, floor attenuation, detection thresholds) are edited in the dashboard under **Settings**. Defaults and meanings are in [DEEP_DIVE.md §19](../DEEP_DIVE.md#19-configuration-reference).

**Database migrations.** SQLite creates its tables automatically. Postgres uses Alembic: run `alembic upgrade head`. The Compose `migrate` service does this for you.

---

## Interfaces

- **REST:** 51 endpoints under `/api`. The full spec is in [`contracts/openapi.json`](contracts/openapi.json), and Swagger UI is at `/docs`.
- **Socket.IO:**
  - connect with `auth: {token}`, or `{signage_token}` for displays;
  - phones send `scan`, `gps`, `manual_location` and `floor_confirm`;
  - the server sends `snapshot`, `route.assigned`, `position.fix`, `hazards`, `incident.updated`, `signage.update`, `sos.created` and more.

  Every server event has a JSON Schema in [`contracts/events.schema.json`](contracts/events.schema.json), and the tests validate real engine output against those schemas.
- **Sensors:** see below.

### Sensors

Register a sensor in the dashboard or use a seeded one, then post readings:

```bash
curl -X POST http://localhost:5000/api/sensors/8/readings -H "X-Sensor-Key: <key>" -H "Content-Type: application/json" -d '{"smoke": 420, "temperature_c": 61}'
```

A node is on fire when any of these holds:
- smoke ≥ 300;
- temperature ≥ 57 °C;
- temperature rising ≥ 8 °C/min;
- `flame: true`;
- `alarm: true` from an alarm-panel relay.

When that happens:
1. the hazard is set to fire;
2. an incident opens, if none is active;
3. every resident is alerted;
4. routes avoid the area within about a second.

Over MQTT, publish to `sensors/<id>/reading` with `{"key": "...", "smoke": ..., "temperature_c": ...}`.

To use an **existing** fire alarm panel, have an ESP32 read the panel's relay (dry-contact) output and send `{"alarm": true}`.

### Push notifications (optional)

Without push, alarms still reach phones that have the app open, over the socket. To enable push:

1. Create a free Firebase project and add an Android app with package name `com.smartfireevac.app`.
2. Put `google-services.json` in `MainProjectFlutter/android/app/` and rebuild the app.
3. Generate a service-account key and save it as `fire-backend/secrets/firebase-service-account.json`. The `secrets/` folder is git-ignored.
4. Set `FIREBASE_CREDENTIALS=secrets/firebase-service-account.json`.

---

## Wi-Fi positioning in practice

- **Privacy:** positions are processed **only during an incident or drill, or in Simulation mode**. Phone position state is wiped at all-clear, and history is deleted after `POSITION_RETENTION_DAYS`.
- **Scan limits:** Android allows a foreground app only **4 Wi-Fi scans per 2 minutes**. On demo phones, turn off *Developer options → Wi-Fi scan throttling* to get roughly a scan every 3 s.
- **Survey and calibrate:**
  1. Map router positions: stand next to each router in the app's survey mode, or place them in the dashboard editor.
  2. Record about 20 survey scans per room.
  3. Press **Calibrate** in the editor. It fits P_ref and η per router and reports fingerprint accuracy from cross-validation.
- **When Wi-Fi isn't good enough** (power cut, unknown routers), the server asks the phone to show **"Where are you?"**. A manual pick overrides GPS for 60 s.

---

## Tests, evaluation and tools

| Command | What it does |
|---|---|
| `.venv/Scripts/python -m pytest` | 37 tests: A\* matches Dijkstra from every node, admissible heuristic, the paper's equations, particle filter convergence, manual pick beating GPS-outside, simulator, API flows end to end, event-contract validation |
| `.venv/Scripts/python -m ruff check .` | Lint |
| `.venv/Scripts/python -m app.simulation.benchmark --seeds 20` | Table I comparison (static plan vs dynamic A\*) plus positioning accuracy; see [EVALUATION.md](EVALUATION.md) |
| `.venv/Scripts/python -m scripts.train_congestion --runs 40` | Trains the predictive congestion model into `ml_models/` |
| `.venv/Scripts/python -m scripts.export_contracts` | Regenerates `contracts/openapi.json` and `events.schema.json` |
| `.venv/Scripts/python -m scripts.make_fixtures` | Regenerates the demo building graphs |
| `.venv/Scripts/python -m scripts.make_route_cases` | Regenerates the route test vectors the app's offline A\* must match |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Phone can't connect | Same Wi-Fi? Firewall rule for port 5000? Use the LAN IP, not `localhost`. An emulator uses `10.0.2.2`. |
| Dashboard shows "STALE DATA" | The backend isn't running or the socket dropped. Start `run.py`. With Docker, check that `engine` is up and `REDIS_URL` is set. |
| Socket.IO handshake rejected (400) | Add the dashboard's origin to `CORS_ORIGINS`. |
| Phone shows "Location tracking is only active during an incident" | Expected, for privacy. Start a drill, or switch the building to Simulation mode. |
| App says "session expired" after `seed --reset` | Expected: reseeding wipes refresh tokens. Sign in again. |
| Times off by your timezone | Already handled: datetimes are stored and returned as UTC-aware. Make sure you're on the latest code. |

---

## Layout

```
app/
  auth/          JWT, roles, join code, approval queue
  buildings/     society → building → floor → node/edge graph, editor publish, floor plans
  positioning/   rssi (eq. 1-5), trilateration (Alg. 3), particle filter (Alg. 1), fingerprint kNN, fallback
  routing/       graph, A* (Alg. 2), cost model, steps, route cache
  congestion/    density, predictive model
  engine/        1 Hz loop, router (runs in-process or as `python -m app.engine`)
  simulation/    virtual occupants, fire spread, synthetic RSSI, benchmark
  sensors/       detection rules, HTTP ingest, MQTT bridge, hazards
  incidents/     lifecycle, participants, SOS, event log, metrics
  realtime/      Socket.IO handlers, emitter, event schemas
  signage/       digital signage
contracts/       OpenAPI, event schemas, demo buildings, route cases (shared with dashboard + app)
migrations/      Alembic
scripts/         seed, fixtures, contracts, route cases, model training
tests/           pytest
```
