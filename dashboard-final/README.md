# Evacuation Command Dashboard

This is the dashboard for rescuers and society admins in the **AI-Driven Smart Fire Evacuation System** (IEEE ICSCC 2025). It is built with Next.js (App Router), TypeScript, Tailwind v4 and shadcn-style components. It talks to the Flask backend in `../fire-backend`.

> Not a certified life-safety system.

| Page | What it does | Paper |
|---|---|---|
| `/buildings/[id]` | The **live command view**. It shows:<ul><li>KPIs: active devices, average path length, congestion rate, fire alerts, evacuated, unaccounted, needing help;</li><li>the floor map with hazards, people and congestion;</li><li>exit capacity;</li><li>SOS requests and residents not yet safe;</li><li>the device table with assigned exit and path progress.</li></ul>Click a room to mark fire or smoke. Click a person to see their route. | Fig. 3 and Fig. 4, §III-E |
| `/buildings/[id]/simulation` | Switch Live/Simulation, spawn occupants, click to ignite, set speed, and run the **static vs dynamic benchmark** | §VII, Table I |
| `/buildings/[id]/incidents`, `/incidents/[id]` | Incident history, post-incident metrics, **replay**, CSV export | §IV-4 |
| `/buildings/[id]/sensors` | Sensor registry, API keys, live readings | §IV-1 |
| `/buildings/[id]/signage` and `/signage/[token]` | Manage displays, and the full-screen display page for TVs and tablets | §III-E |
| `/buildings/[id]/editor` | **Floor-plan editor**:<ul><li>place rooms, corridors, stairs, lifts, exits, refuges and routers;</li><li>connect them, including across floors;</li><li>upload plan images;</li><li>import/export JSON, validate and publish;</li><li>calibrate Wi-Fi from survey data.</li></ul> | §III-C graph model |
| `/buildings/[id]/settings` | A\* weights (α, β, γ), congestion threshold, rerouting safeguards, positioning and detection thresholds | §III-C/D |
| `/residents` | Approval queue, mobility needs, staff accounts | |

## Run

1. Start the backend first (see `../fire-backend/README.md`).
2. Install dependencies:
   ```bash
   npm install
   ```
3. Create `.env.local` with:
   ```
   NEXT_PUBLIC_API_URL=http://localhost:5000
   API_URL=http://localhost:5000
   ```
4. Start the dev server:
   ```bash
   npm run dev
   ```

Then open http://localhost:3000 and sign in with `admin@example.com` or `rescuer@example.com`. The password is `Evacuate@123`; these accounts are created by the backend seed.

## How it fits together

- **Auth.** `/session/login` exchanges credentials with Flask and stores the JWTs in **httpOnly cookies**. `proxy.ts` sends anyone without a session to the login page.
- **REST.** Every call goes through the **BFF** at `/bff/*`, a route handler that attaches the token and refreshes it once on a 401. Browser code never sees the refresh token.
- **Realtime.** There is one Socket.IO connection (`lib/realtime/socket-provider.tsx`) straight to Flask:
  - it fetches a short-lived token from `/session/token` on every reconnect;
  - incoming snapshots are validated with zod (`lib/schemas.ts`);
  - malformed messages are dropped, never rendered half-way.
- **Stale data.** If the socket drops, or no snapshot arrives for 5 s, the view shows a **STALE DATA** banner and greys out the map. An empty map is never shown as "all clear".
- **Contracts.** `lib/types.ts` mirrors `fire-backend/contracts/events.schema.json`. `npm test` checks that the required fields still match.

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` / `npm run build` / `npm start` | Develop / build / run |
| `npm run typecheck` / `npm run lint` | Static checks |
| `npm test` | Vitest unit tests |
| `npm run gen:api` | Regenerate `lib/api/openapi.d.ts` from the backend OpenAPI |
