import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { STALE_AFTER_MS, isStale } from "./realtime/store";
import { SnapshotSchema } from "./schemas";

describe("stale data detection (rescuers must never see an empty map as 'all clear')", () => {
  it("is stale when disconnected even with fresh data", () => {
    expect(isStale(Date.now(), "disconnected")).toBe(true);
  });
  it("is stale before the first snapshot", () => {
    expect(isStale(undefined, "connected")).toBe(true);
  });
  it("is fresh within the window and stale after it", () => {
    const now = 1_000_000;
    expect(isStale(now - 1000, "connected", now)).toBe(false);
    expect(isStale(now - STALE_AFTER_MS - 1, "connected", now)).toBe(true);
  });
});

describe("snapshot validation", () => {
  const base = {
    ts: 1,
    building_id: 2,
    name: "Tower",
    mode: "live",
    graph_version: 1,
    hazard_version: 1,
    incident: null,
    kpis: {
      active_devices: 0, real_devices: 0, virtual_occupants: 0, avg_path_length_m: 0, avg_path_nodes: 0, congestion_rate: 0,
      fire_alerts: 0, evacuated: 0, unaccounted: 0, needs_help: 0, trapped: 0, in_refuge: 0, route_cache_hit_rate: 0,
    },
    hazards: { "5": "fire" },
    occupancy: {},
    congestion: {},
    predicted_congestion: {},
    exits: [],
    devices: [],
    unaccounted: [],
    sos: [],
    sim: null,
    reroutes: {},
  };

  it("accepts a valid snapshot", () => {
    expect(SnapshotSchema.safeParse(base).success).toBe(true);
  });
  it("rejects partial payloads instead of crashing the view", () => {
    const partial: Record<string, unknown> = { ...base };
    delete partial.kpis;
    expect(SnapshotSchema.safeParse(partial).success).toBe(false);
    expect(SnapshotSchema.safeParse({ ...base, hazards: { "5": "lava" } }).success).toBe(false);
  });
  it("agrees with the backend contract on required snapshot fields", () => {
    const path = join(__dirname, "../../fire-backend/contracts/events.schema.json");
    let contract: { events: { snapshot: { required: string[] } } };
    try {
      contract = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      return; // backend repo not checked out next to the dashboard
    }
    const ours = Object.keys(SnapshotSchema.shape);
    for (const field of contract.events.snapshot.required) expect(ours).toContain(field);
  });
});
