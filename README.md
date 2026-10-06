# AI-Driven Smart Fire Evacuation System: revamped

This is a working implementation of the IEEE ICSCC 2025 paper *AI-Driven Smart Fire Evacuation System*. It has three parts:

| Folder | What it is | Paper |
|---|---|---|
| `fire-backend/` | Flask + Flask-SocketIO server and engine. It does Wi-Fi positioning (eq. 1–5, particle filter Alg. 1, triangulation Alg. 3, learned fingerprinting), routing (A\* Alg. 2 with hazard and congestion costs and exit balancing), sensor ingest, a simulator, incident logging and replay | §III–VII |
| `dashboard-final/` | Next.js (TypeScript) command dashboard for rescuers and society admins: live view, simulation, floor-plan editor, incidents and replay, sensors, signage, residents | Fig. 3/4, §III-E |
| `MainProjectFlutter/` | Android app for residents: full-screen alarm, live route, fallback chain (Wi-Fi, then GPS, then "Where are you?"), SOS / I'm safe, offline routing, survey mode | Fig. 5, §III-B, §IV-4 |

Each folder has its own README. [fire-backend/EVALUATION.md](fire-backend/EVALUATION.md) has the reproducible Table I comparison.

> **Not a certified life-safety system.** It adds to, and does not replace, fire alarms and fire services.

**Paper:** Bhavan S, Nandhana KP, Ria Stanly Keecheril, Rohit Babu George, Asha Raj, "AI-Driven Smart Fire Evacuation System", *2025 11th International Conference on Smart Computing and Communications (ICSCC)*, IEEE. DOI: [10.1109/ICSCC66177.2025.11233739](https://doi.org/10.1109/ICSCC66177.2025.11233739). The PDF is not included because the IEEE copy is licensed.

## Run everything on one laptop (no Docker)

1. **Backend**, in `fire-backend/` (Windows paths shown):
   1. Create the virtual environment and install the dependencies:
      ```bash
      python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
      ```
   2. Create the demo society. It prints the logins, sensor keys and signage links:
      ```bash
      .venv/Scripts/python -m scripts.seed
      ```
   3. Start the server on `0.0.0.0:5000`:
      ```bash
      .venv/Scripts/python run.py
      ```
2. **Dashboard**, in `dashboard-final/`:
   1. Install dependencies:
      ```bash
      npm install
      ```
   2. Create `.env.local` with:
      ```
      NEXT_PUBLIC_API_URL=http://localhost:5000
      API_URL=http://localhost:5000
      ```
   3. Start it, then open http://localhost:3000 and log in as `admin@example.com` / `Evacuate@123`:
      ```bash
      npm run dev
      ```
3. **App**: build it in `MainProjectFlutter/`:
   ```bash
   flutter build apk --release
   ```
   Install the APK on Android phones on the **same Wi-Fi**. Enter `http://<laptop-LAN-IP>:5000` and log in as `resident.b1@example.com`. Allow port 5000 through Windows Firewall.

With Docker Desktop running, `fire-backend/docker-compose.yml` starts Postgres, Redis, the API, a separate engine process and the dashboard instead.

## Demo script (about 10 minutes)

1. **Dashboard → Block A → Simulation.**
   - Switch to *Simulation* and **Start** with 40 occupants.
   - Click the **Kitchen** to start a fire.
   - The fire opens an incident on its own: smoke spreads, people are split across exits, queues form, and the KPI tiles update live.
2. **Signage.** Open a display link from *Signage* on a second screen. The arrow points to the safest exit and updates as the fire spreads.
3. **Phones.**
   1. Log in on two phones (`resident.b1`, `resident.b2` in Block B).
   2. On the dashboard, open **Block B → Alert residents → Start a drill**.
   3. Both phones show the full-screen alarm. Tap **EVACUATE NOW**.
   4. Each phone sees its route. `resident.b2` is a wheelchair user and gets a refuge route.
   5. Tap a corridor on the dashboard and mark it **Fire**. Within about a second the phones reroute, and the banner explains why.
4. **Fallback.**
   - Stop the backend. After 10 s the phones show "OFFLINE - route computed on this phone".
   - Use **Set my location** to see the manual picker.
5. **Close out.**
   - Tap **I'M SAFE** on the phones.
   - Declare **All clear** on the dashboard.
   - Open **Incidents → Replay** to scrub through the evacuation, and export the CSV.
6. **Table I.** Run the benchmark from the simulation page, or run `python -m app.simulation.benchmark --seeds 20`.

## Tests

| Part | Command | Covers |
|---|---|---|
| Backend | `.venv/Scripts/python -m pytest` | 36 tests: A\* = Dijkstra on every node, paper equations, particle filter convergence, the API flows end to end, event contracts |
| Dashboard | `npm test && npm run typecheck && npm run lint && npm run build` | |
| App | `flutter test && flutter analyze` | Offline A\* gives exactly the server's routes and costs |
