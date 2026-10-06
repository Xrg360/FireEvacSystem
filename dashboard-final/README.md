# Evacuation Command Dashboard

This is the rescuer and society-admin dashboard for the **AI-Driven Smart Fire Evacuation System** (IEEE ICSCC 2025). It gives a live view of every resident, hazard, exit and SOS call during an evacuation, plus simulation, a floor-plan editor, incident replay and digital signage.

It is part of the [FireEvacSystem monorepo](../README.md) and talks to the Flask server in [`../fire-backend`](../fire-backend). Technical details are in [DEEP_DIVE.md §15](../DEEP_DIVE.md#15-dashboard-architecture).

> ⚠️ Not a certified life-safety system. Always follow fire service instructions.

<img src="../docs/screenshots/dashboard-live-tower.jpg" alt="Live command view of a 4-storey tower during a simulated fire" width="100%"/>

---

## Pages

| Page | What it does | Paper |
|---|---|---|
| `/` | Society overview: buildings, mode (Live/Simulation), active incidents, resident join code | |
| `/buildings/[id]` | **Live command view.** It shows:<ul><li>KPIs: active devices, average path length, congestion rate, fire alerts, evacuated, unaccounted, need help, trapped / in refuge;</li><li>a per-floor map with hazards, people (real phones and simulated occupants), congestion and predicted congestion;</li><li>exit capacity, SOS requests and the not-yet-safe list;</li><li>a device table with assigned exit and path progress.</li></ul>**Click a room** to mark fire, smoke or risk, or clear it. **Click a person** to see their route. | Fig. 3, Fig. 4, §III-E |
| `/buildings/[id]/simulation` | Switch Live/Simulation; spawn occupants (including "virtual phones" that run real positioning); click to ignite or extinguish; speed and spread controls; one-click **static vs dynamic benchmark** | §VII, Table I |
| `/buildings/[id]/incidents`, `/incidents/[id]` | Incident history, post-incident metrics, **replay timeline**, event log, CSV export | §IV-4 |
| `/buildings/[id]/sensors` | Sensor registry, API keys (shown once, rotatable), live smoke and temperature charts, alarm state, clear all hazards | §IV-1 |
| `/buildings/[id]/signage`, `/signage/[token]` | Manage displays, and the public full-screen kiosk page with a live arrow to the safest exit | §III-E |
| `/buildings/[id]/editor` | **Floor-plan editor** (admin):<ul><li>place rooms, corridors, stairs, lifts, exits, refuges and routers;</li><li>connect them, including across floors;</li><li>move nodes; add floors; upload plan images;</li><li>import/export JSON, validate and publish;</li><li>calibrate Wi-Fi from survey data;</li><li>show survey counts per room.</li></ul> | §III-C |
| `/buildings/[id]/settings` | A\* weights (α, β, γ), congestion threshold, reroute safeguards, positioning and detection thresholds (admin) | §III-C/D |
| `/residents` | Approval queue, mobility needs ("can't use stairs"), staff accounts (admin) | |

| Simulation and benchmark | Incident replay |
|---|---|
| <img src="../docs/screenshots/dashboard-simulation.jpg" alt="Simulation console"/> | <img src="../docs/screenshots/dashboard-replay.jpg" alt="Replay"/> |
| **Floor-plan editor** | **Sensors** |
| <img src="../docs/screenshots/dashboard-editor.jpg" alt="Editor"/> | <img src="../docs/screenshots/dashboard-sensors.jpg" alt="Sensors"/> |
| **Signage display** | **Resident approvals** |
| <img src="../docs/screenshots/signage-display.jpg" alt="Signage"/> | <img src="../docs/screenshots/dashboard-residents.jpg" alt="Residents"/> |

---

## Run

Start the backend first (see [`../fire-backend/README.md`](../fire-backend/README.md)). You need Node 20 or later.

1. Install dependencies:
   ```bash
   npm install
   ```
2. Create `.env.local` (see [Environment](#environment)):
   ```
   NEXT_PUBLIC_API_URL=http://localhost:5000
   API_URL=http://localhost:5000
   ```
3. Start the dev server:
   ```bash
   npm run dev
   ```

Open http://localhost:3000 and sign in with `admin@example.com` (admin) or `rescuer@example.com` (rescuer). The password is `Evacuate@123`; both accounts come from the backend seed. Resident accounts are refused here, because residents use the mobile app.

### Production

```bash
npm run build
```

```bash
npm start
```

`next.config.ts` uses `output: "standalone"`. The included `Dockerfile` builds a small Node image; the backend's `docker-compose.yml` builds it automatically as the `dashboard` service.

### Environment

| Variable | Where it's used | Example |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Browser: the Socket.IO connection and plan images | `http://localhost:5000` or `https://api.example.org` |
| `API_URL` | Next.js server: the BFF proxy and login | `http://localhost:5000`, or `http://api:5000` in Docker |
| `COOKIE_SECURE` | Set to `1` to mark session cookies `Secure` (needed behind HTTPS) | `1` |

The dashboard's origin must be listed in the backend's `CORS_ORIGINS`.

---

## How it fits together

- **Auth.**
  - `/session/login` exchanges credentials with Flask and stores the access and refresh JWTs in **httpOnly cookies**.
  - `proxy.ts` (Next 16's middleware) sends anyone without a session to `/login`.
  - Real authorisation is done by Flask on every request.
- **REST.** Every call goes through the **BFF** at `/bff/*` (`app/bff/[...path]/route.ts`). It attaches the token, refreshes it once on a 401, and passes CSV downloads and image uploads through. Browser code never sees the refresh token.
- **Realtime.** There is one shared Socket.IO connection (`lib/realtime/socket-provider.tsx`) straight to Flask:
  - it fetches a short-lived token from `/session/token` on every reconnect;
  - `useBuildingSubscription` joins a building's room and re-subscribes after reconnects;
  - snapshots are validated with zod (`lib/schemas.ts`); malformed payloads are dropped, never half-rendered.
- **Stale data.** If the socket drops or no snapshot arrives for **5 s**, the view shows **STALE DATA** and greys out the map. An empty map must never read as "all clear".
- **Maps.** `components/floor-map.tsx` is a single SVG component drawn in metre coordinates, used by the live view, simulation, replay and the editor.
- **Contracts.** `lib/types.ts` mirrors `fire-backend/contracts/events.schema.json`, and `npm test` checks that the snapshot's required fields still match. `npm run gen:api` regenerates `lib/api/openapi.d.ts` from the backend's OpenAPI spec.

### Project structure

```
app/
  (app)/                 authenticated pages (overview, buildings/[id]/..., incidents/[id], residents)
  bff/[...path]/         backend-for-frontend proxy to Flask
  session/               login / logout / socket token route handlers
  signage/[token]/       public kiosk display
  login/                 sign-in page
components/              app shell, floor map, ui primitives
features/live/           KPI row, side panels, device table, incident bar, hazard dialog, floor tabs
lib/                     api client, hooks, realtime store + socket, zod schemas, types
proxy.ts                 auth redirect
```

---

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Dev server (Turbopack) |
| `npm run build` / `npm start` | Production build / serve |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint (Next core-web-vitals + TypeScript) |
| `npm test` | Vitest: 6 tests (stale-data rules, payload validation, contract parity) |
| `npm run gen:api` | Regenerate OpenAPI types |

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Cannot reach the evacuation server" at login | Start the backend, and check `API_URL`. |
| Permanent **STALE DATA** / "Disconnected" | Check `NEXT_PUBLIC_API_URL` (it must be reachable from the browser) and that the dashboard origin is in the backend's `CORS_ORIGINS`. |
| Logged out right after logging in, behind HTTPS | Set `COOKIE_SECURE=1`. If you're on plain http, leave it unset. |
| Dev server stops responding after a long idle | Restart `npm run dev`, or use `npm run build && npm start` for demos. |
| Floor-plan image doesn't show | Images are served by the backend at `/uploads/...`. Check `NEXT_PUBLIC_API_URL`. |
