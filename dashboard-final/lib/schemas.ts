// Runtime validation of socket payloads. A malformed or partial message must never crash the
// rescuer view (the old dashboard crashed on a missing `coordinates`); bad payloads are dropped
// and counted, and the UI keeps showing the last good snapshot marked as stale.
import { z } from "zod";

const num = z.number();
const nullableNum = z.number().nullable();

export const KpisSchema = z.object({
  active_devices: num,
  real_devices: num,
  virtual_occupants: num,
  avg_path_length_m: num,
  avg_path_nodes: num,
  congestion_rate: num,
  fire_alerts: num,
  evacuated: num,
  unaccounted: num,
  needs_help: num,
  trapped: num,
  in_refuge: num,
  route_cache_hit_rate: num,
});

export const LiveDeviceSchema = z.looseObject({
  id: z.string(),
  kind: z.enum(["real", "virtual"]),
  name: z.string(),
  x: nullableNum,
  y: nullableNum,
  level: z.number().int().nullable(),
  node_id: z.number().int().nullable(),
  source: z.string(),
  confidence: num,
  status: z.string(),
  stairs_ok: z.boolean(),
  route: z.array(z.number().int()),
  goal: z.number().int().nullable(),
  goal_type: z.string().nullable(),
  remaining_m: nullableNum,
  progress: nullableNum,
});

export const SnapshotSchema = z.looseObject({
  ts: num,
  building_id: z.number().int(),
  name: z.string(),
  mode: z.enum(["live", "simulation"]),
  graph_version: z.number().int(),
  hazard_version: z.number().int(),
  incident: z.looseObject({ id: z.number().int(), kind: z.string().nullable(), started_at: nullableNum }).nullable(),
  kpis: KpisSchema,
  hazards: z.record(z.string(), z.enum(["risk", "smoke", "fire"])),
  occupancy: z.record(z.string(), num),
  congestion: z.record(z.string(), num),
  predicted_congestion: z.record(z.string(), num),
  exits: z.array(
    z.object({
      node_id: z.number().int(),
      name: z.string(),
      assigned: num,
      queue: num,
      flow_per_min: num,
      capacity: num,
      hazard: z.string(),
    }),
  ),
  devices: z.array(LiveDeviceSchema),
  unaccounted: z.array(z.any()),
  sos: z.array(z.any()),
  sim: z.any().nullable(),
  reroutes: z.record(z.string(), num),
});

export const SignageSchema = z.looseObject({
  status: z.enum(["normal", "evacuate", "exit", "danger"]),
  message: z.string(),
  arrow_deg: nullableNum,
});
