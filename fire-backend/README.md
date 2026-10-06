# fire-backend

This is the Flask server for the **AI-Driven Smart Fire Evacuation System** (IEEE ICSCC 2025). It is the "centralized processing server" in the paper.

> **Not a certified life-safety system.** It adds to, and does not replace, fire alarms, fire exits and the instructions of trained responders.

| Paper | Where it lives |
|---|---|
| Eq. 1/3: RSSI to distance; eq. 4/5: distance bounds | `app/positioning/rssi.py` |
| Alg. 1: particle filter (with eq. 4/5 likelihood + floor attenuation) | `app/positioning/particle_filter.py` |
| Alg. 3: weighted triangulation | `app/positioning/trilateration.py` |
| Learned Wi-Fi fingerprinting (kNN), the addition to the paper | `app/positioning/fingerprint.py` |
| Fallback chain: Wi-Fi, then GPS, then manual pick | `app/positioning/fallback.py` |
| Alg. 2: A\* (eq. 2), multi-floor, admissible heuristic | `app/routing/astar.py`, `app/routing/graph.py` |
| Hazard and congestion costs, refuge routing for residents who can't use stairs | `app/routing/planner.py` |
| Congestion threshold, rerouting, safeguards against flip-flopping between routes | `app/engine/router.py` |
| Predictive congestion (Table II), the addition to the paper | `app/congestion/predict.py`, `scripts/train_congestion.py` |
| §VI WebSocket publish/subscribe | `app/realtime/` (Flask-SocketIO, with Redis as the message queue) |
| §IV system flow (collect, process, plan, output) | `app/engine/engine.py` |
| §III-E digital signage | `app/signage/`, plus the dashboard page `/signage/<token>` |
| §IV-4 post-incident logging | `app/incidents/` (event log, replay, metrics, CSV export) |
| Fire sensors (HTTP and optional MQTT) | `app/sensors/` |
| §VII simulated evaluation (Table I) | `app/simulation/benchmark.py` |

## Run it

### Option A: local, no Docker (SQLite, engine runs inside the API process)

On Windows, use `.venv\Scripts\...` in place of `.venv/bin/...`.

1. Create a virtual environment and install the dependencies:
   ```bash
   python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
   ```
2. Create the demo society. It prints the logins, sensor keys and signage tokens:
   ```bash
   .venv/Scripts/python -m scripts.seed
   ```
3. Start the API, Socket.IO and the engine on `0.0.0.0:5000`:
   ```bash
   .venv/Scripts/python run.py
   ```

API documentation is at http://localhost:5000/docs.

### Option B: Docker Compose (Postgres, Redis, separate engine process, dashboard)

1. Create `.env` and set `JWT_SECRET` (and `FIREBASE_CREDENTIALS` if you use push):
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
4. Optional: add the MQTT sensor broker:
   ```bash
   docker compose --profile mqtt up
   ```

**Phones must be on the same Wi-Fi as the laptop.** Point the app at `http://<laptop-LAN-IP>:5000`, and allow port 5000 through Windows Firewall.

### Demo accounts

These are created by `scripts.seed`. The password for all of them is `Evacuate@123`, and the join code is `MITS2025`.

| Email | Role |
|---|---|
| admin@example.com | Society admin (approvals, editor, settings) |
| rescuer@example.com | Rescuer (live command view, SOS) |
| surveyor@example.com | Surveyor (Wi-Fi survey mode in the app) |
| resident.b1@example.com | Resident, Block B flat 302 |
| resident.b2@example.com | Resident, Block B, wheelchair user (routed to refuge areas) |
| resident.a@example.com | Resident, Block A villa |

## Push notifications (FCM)

Push is optional. Without it, alarms still reach phones that have the app open, over the socket. To enable it:

1. Create a free Firebase project and add an Android app with package name `com.smartfireevac.app`.
2. Download `google-services.json` into `MainProjectFlutter/android/app/`.
3. In Project settings → Service accounts, generate a private key. Save it as `fire-backend/secrets/firebase-service-account.json`. That folder is git-ignored.
4. Set `FIREBASE_CREDENTIALS=secrets/firebase-service-account.json` in `.env`.

## Sensors

Register a sensor in the dashboard (or use one of the seeded sensors), then post readings:

```bash
curl -X POST http://localhost:5000/api/sensors/8/readings -H "X-Sensor-Key: <key>" -H "Content-Type: application/json" -d '{"smoke": 420, "temperature_c": 61}'
```

A reading counts as fire if any of these holds:
- smoke is at or above the threshold;
- temperature is at or above 57 °C;
- temperature is rising by 8 °C/min or more;
- the flame sensor or alarm-panel relay reports true.

When that happens, the node's hazard is set to fire, an incident opens and residents are alerted.

Over MQTT, publish to `sensors/<id>/reading` with the payload `{"key": "...", "smoke": ..., "temperature_c": ...}`.

The realistic way to use an **existing** fire alarm panel is an ESP32 reading the panel's relay (dry-contact) output and sending `{"alarm": true}`.

## Wi-Fi positioning in practice

- Android limits apps to **4 Wi-Fi scans per 2 minutes** in the foreground. On demo phones, turn this off in *Developer options → Wi-Fi scan throttling*.
- Map the routers: either stand next to each router in the app's survey mode, or place them in the dashboard editor.
- Survey about 20 scans per room. Then run **Calibrate** in the dashboard: it fits P_ref/η for each router (eq. 1) and reports fingerprint accuracy from cross-validation.
- Positions are only processed **during an incident or drill**, or in Simulation mode. Position history is deleted after `POSITION_RETENTION_DAYS`.

## Tests and evaluation

```bash
.venv/Scripts/python -m pytest
```

The suite covers A\* against Dijkstra, the paper's equations, particle filter convergence, the API flows end to end, and event-contract validation.

```bash
.venv/Scripts/python -m app.simulation.benchmark --seeds 20
```

This produces the Table I comparison (static plan vs dynamic routing), described in [EVALUATION.md](EVALUATION.md).

```bash
.venv/Scripts/python -m scripts.train_congestion --runs 40
```

This trains the predictive congestion model.

```bash
.venv/Scripts/python -m scripts.export_contracts
```

This regenerates `contracts/openapi.json` and `contracts/events.schema.json`.

## Layout

```
app/
  auth/          JWT, roles, join code, approval queue
  buildings/     society → building → floor → node/edge graph, editor publish
  positioning/   rssi (eq. 1-5), trilateration (Alg. 3), particle filter (Alg. 1), fingerprint kNN, fallback
  routing/       graph, A* (Alg. 2), cost model, steps, route cache
  congestion/    density, predictive model
  engine/        per-tick loop and router (runs in-process or as `python -m app.engine`)
  simulation/    virtual occupants, fire spread, synthetic RSSI, benchmark
  sensors/       detection rules, HTTP ingest, MQTT bridge, hazards
  incidents/     lifecycle, participants, SOS, event log, metrics
  realtime/      Socket.IO handlers, emitter, event schemas
  signage/       digital signage
contracts/       OpenAPI, event JSON schemas, demo building fixtures (shared with dashboard + app)
scripts/         seed, fixtures, contracts export, model training
```
