// Mirrors fire-backend: app/realtime/schemas.py (events) and REST payloads.
// Event schemas are exported to fire-backend/contracts/events.schema.json.

export type Role = "resident" | "surveyor" | "rescuer" | "society_admin";
export type HazardLevel = "none" | "risk" | "smoke" | "fire";
export type NodeType = "room" | "corridor" | "stair" | "lift" | "exit" | "refuge" | "assembly";
export type EdgeKind = "door" | "corridor" | "stair" | "lift" | "outdoor";
export type IncidentStatus = "detected" | "evacuating" | "all_clear" | "closed";
export type ParticipantStatus = "unknown" | "evacuating" | "safe" | "needs_help";

export interface User {
  id: number;
  email: string;
  name: string;
  phone: string | null;
  role: Role;
  status: "pending" | "approved" | "rejected";
  society_id: number | null;
  building_id: number | null;
  flat: string | null;
  home_node_id: number | null;
  stairs_ok: boolean;
  mobility_notes: string | null;
  created_at: string | null;
}

export interface Me {
  user: User;
  society: { id: number; name: string; join_code: string | null } | null;
  building: { id: number; name: string; mode: string } | null;
}

export interface BuildingSettings {
  alpha: number;
  beta: number;
  gamma: number;
  congestion_threshold: number;
  reroute_improvement: number;
  reroute_cooldown_s: number;
  rssi_uncertainty_db: number;
  floor_attenuation_db: number;
  particles: number;
  low_confidence: number;
  floor_confirm_confidence: number;
  smoke_threshold: number;
  temp_threshold_c: number;
  rate_of_rise_c_per_min: number;
}

export interface Incident {
  id: number;
  building_id: number;
  kind: "fire" | "drill";
  status: IncidentStatus;
  is_simulation: boolean;
  trigger: Record<string, unknown> | null;
  started_at: string | null;
  ended_at: string | null;
  metrics?: IncidentMetrics | null;
}

export interface IncidentMetrics {
  duration_s: number | null;
  residents: number;
  status_counts: Record<string, number>;
  avg_evac_time_s: number | null;
  max_evac_time_s: number | null;
  avg_ack_time_s: number | null;
  route_assignments: number;
  reroutes_by_reason: Record<string, number>;
  avg_route_update_latency_ms: number | null;
  p95_route_update_latency_ms: number | null;
  simulation: Record<string, unknown> | null;
}

export interface Building {
  id: number;
  society_id: number;
  name: string;
  mode: "live" | "simulation";
  floor_height_m: number;
  graph_version: number;
  hazard_version: number;
  footprint: [number, number][] | null;
  settings: BuildingSettings;
  incident: Incident | null;
}

export interface Floor {
  id: number;
  level: number;
  name: string;
  width_m: number;
  height_m: number;
  plan_image?: string | null;
  scale_px_per_m?: number | null;
}

export interface GraphNode {
  id: number;
  key: string;
  name: string;
  type: NodeType;
  floor_id: number;
  x: number;
  y: number;
  capacity: number;
  exit_flow_per_min: number | null;
  lat: number | null;
  lng: number | null;
}

export interface GraphEdge {
  id?: number;
  a: number;
  b: number;
  kind: EdgeKind;
  length_m: number | null;
  width_m: number;
  accessible: boolean;
}

export interface AccessPoint {
  id?: number;
  bssid: string;
  ssid: string | null;
  floor_id: number;
  x: number;
  y: number;
  p_ref: number;
  eta: number;
  calibrated?: boolean;
  enabled?: boolean;
}

export interface Graph {
  building: { id: number; name: string; floor_height_m: number; graph_version: number; footprint: [number, number][] | null };
  floors: Floor[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  access_points: AccessPoint[];
}

// ---------------------------------------------------------------- live (socket) payloads

export interface Kpis {
  active_devices: number;
  real_devices: number;
  virtual_occupants: number;
  avg_path_length_m: number;
  avg_path_nodes: number;
  congestion_rate: number;
  fire_alerts: number;
  evacuated: number;
  unaccounted: number;
  needs_help: number;
  trapped: number;
  in_refuge: number;
  route_cache_hit_rate: number;
}

export interface ExitInfo {
  node_id: number;
  name: string;
  assigned: number;
  queue: number;
  flow_per_min: number;
  capacity: number;
  hazard: string;
}

export interface LiveDevice {
  id: string;
  kind: "real" | "virtual";
  name: string;
  flat?: string | null;
  phone?: string | null;
  x: number | null;
  y: number | null;
  level: number | null;
  node_id: number | null;
  source: string;
  confidence: number;
  spread_m?: number | null;
  outside?: boolean;
  needs_picker?: boolean;
  status: string;
  stairs_ok: boolean;
  route: number[];
  goal: number | null;
  goal_type: string | null;
  remaining_m: number | null;
  progress: number | null;
  is_phone?: boolean;
  gps?: { lat: number; lng: number; accuracy_m: number } | null;
}

export interface SosRequest {
  id: number;
  building_id: number;
  incident_id: number | null;
  device_id: string;
  user_id: number | null;
  user_name: string | null;
  flat: string | null;
  phone: string | null;
  stairs_ok: boolean;
  kind: "help" | "trapped" | "medical";
  note: string | null;
  node_id: number | null;
  x: number | null;
  y: number | null;
  level: number | null;
  created_at: string;
  resolved_at: string | null;
}

export interface UnaccountedResident {
  device_id: string;
  user_id: number;
  name: string;
  flat: string | null;
  phone: string | null;
  stairs_ok: boolean;
  status: ParticipantStatus;
  last_fix: { node_id: number | null; level: number | null; source: string; x: number | null; y: number | null } | null;
}

export interface SimState {
  running: boolean;
  speed: number;
  t: number;
  alarm_t: number | null;
  summary: SimSummary;
  localization_median_error_m: number | null;
}

export interface SimSummary {
  occupants: number;
  evacuated: number;
  trapped: number;
  in_refuge: number;
  avg_evac_time_s: number | null;
  max_evac_time_s: number | null;
  p90_evac_time_s: number | null;
  avg_exit_queue: number;
  peak_exit_queue: number;
  reroutes: Record<string, number>;
  sim_time_s: number;
}

export interface Snapshot {
  ts: number;
  building_id: number;
  name: string;
  mode: "live" | "simulation";
  graph_version: number;
  hazard_version: number;
  incident: { id: number; kind: string | null; started_at: number | null } | null;
  kpis: Kpis;
  hazards: Record<string, "risk" | "smoke" | "fire">;
  occupancy: Record<string, number>;
  congestion: Record<string, number>;
  predicted_congestion: Record<string, number>;
  exits: ExitInfo[];
  devices: LiveDevice[];
  unaccounted: UnaccountedResident[];
  sos: SosRequest[];
  sim: SimState | null;
  reroutes: Record<string, number>;
}

export interface SignageState {
  signage_id?: number;
  name?: string;
  status: "normal" | "evacuate" | "exit" | "danger";
  message: string;
  arrow_deg: number | null;
  vertical?: "up" | "down" | null;
  next?: string;
  exit?: string;
  distance_m?: number;
  incident?: boolean;
  hazard_here?: string;
  exits?: { name: string; hazard: string; assigned: number }[];
}

export interface Sensor {
  id: number;
  building_id: number;
  node_id: number;
  node_name: string | null;
  name: string;
  type: "smoke" | "temperature" | "flame" | "multi" | "alarm_panel";
  last_reading: { smoke?: number; temperature_c?: number; flame?: boolean; alarm?: boolean } | null;
  triggered: boolean;
  last_seen: string | null;
  api_key?: string;
}

export interface Resident extends User {
  devices: { id: string; model: string | null; app_version: string | null; push: boolean; last_seen: string | null }[];
}

export interface SignageItem {
  id: number;
  building_id: number;
  node_id: number;
  node_name: string | null;
  name: string;
  token?: string;
}

export interface EventLogItem {
  id: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
}
