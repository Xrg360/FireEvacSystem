"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Flame, Loader2, Pause, Play, RotateCcw, Square, Users } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { FloorMap, MapLegend } from "@/components/floor-map";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { FloorTabs } from "@/features/live/floor-tabs";
import { KpiRow } from "@/features/live/kpi-row";
import { api, errorMessage } from "@/lib/api/client";
import { useBuilding, useGraph, useLiveSnapshot, useMe } from "@/lib/hooks";
import { useBuildingSubscription } from "@/lib/realtime/socket-provider";
import { formatDuration } from "@/lib/utils";

interface BenchResult {
  building: string;
  occupants: number;
  seeds: number;
  fire_start: string[];
  table: Record<string, { static: number | null; dynamic: number | null }>;
  exit_queue_reduction_pct: number | null;
  evac_time_reduction_pct: number | null;
  replan_latency_ms_200_people: number;
  positioning: { particle_filter_fused: { median_m: number; p90_m: number }; trilateration: { median_m: number }; fingerprint_knn: { median_m: number }; pf_floor_accuracy: number } | null;
}

const BENCH_ROWS: [string, string][] = [
  ["avg_evac_time_s", "Average evacuation time (s)"],
  ["p90_evac_time_s", "90th percentile evacuation (s)"],
  ["max_evac_time_s", "Total evacuation time (s)"],
  ["avg_exit_queue", "Average exit queue (people)"],
  ["peak_exit_queue", "Peak exit queue (people)"],
  ["trapped", "Trapped by fire"],
  ["in_refuge", "In refuge areas"],
];

export default function SimulationPage() {
  const id = Number(useParams<{ id: string }>().id);
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: building } = useBuilding(id);
  useBuildingSubscription(id);
  const { snapshot } = useLiveSnapshot(id);
  const { data: graph } = useGraph(id, snapshot?.graph_version ?? building?.graph_version);
  const [chosenFloor, setFloorId] = useState<number | null>(null);
  const [occupants, setOccupants] = useState(40);
  const [phoneShare, setPhoneShare] = useState(10);
  const [spread, setSpread] = useState(0.6);
  const [igniteMode, setIgniteMode] = useState(true);
  const [benchJob, setBenchJob] = useState<string | null>(null);
  const [bench, setBench] = useState<BenchResult | null>(null);
  const isAdmin = me?.user.role === "society_admin";
  // benchmark the crowd that is actually in the building when a simulation is running
  const benchOccupants = snapshot?.sim?.summary.occupants || occupants;

  const nodeFloor = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n.floor_id])), [graph]);
  const floorId = chosenFloor ?? (graph ? [...graph.floors].sort((a, b) => a.level - b.level)[0]?.id ?? null : null);

  const setMode = useMutation({
    mutationFn: (mode: "live" | "simulation") => api.patch(`/buildings/${id}`, { mode }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const sim = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/buildings/${id}/simulation`, body),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const runBench = useMutation({
    mutationFn: () =>
      api.post<{ job_id: string }>(`/buildings/${id}/benchmark`, {
        seeds: 5,
        occupants: benchOccupants,
        spread_per_min: spread,
        fire_node_ids: Object.entries(snapshot?.hazards ?? {}).filter(([, l]) => l === "fire").map(([n]) => Number(n)),
      }),
    onSuccess: (r) => {
      setBench(null);
      setBenchJob(r.job_id);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  useEffect(() => {
    if (!benchJob) return;
    const t = setInterval(async () => {
      const job = await api.get<{ status: string; result?: BenchResult; error?: string }>(`/benchmark/${benchJob}`);
      if (job.status === "done" && job.result) {
        setBench(job.result);
        setBenchJob(null);
      } else if (job.status === "failed") {
        toast.error(job.error ?? "Benchmark failed");
        setBenchJob(null);
      }
    }, 1500);
    return () => clearInterval(t);
  }, [benchJob]);

  if (!building || !graph) return <Skeleton className="h-[70vh]" />;
  const floor = graph.floors.find((f) => f.id === floorId) ?? graph.floors[0];
  const s = snapshot?.sim;
  const simMode = building.mode === "simulation";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Simulation - {building.name}</h1>
          <p className="text-sm text-muted-foreground">Virtual occupants use the same routing engine as real phones. Real phones can join the same scenario.</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className={simMode ? "text-muted-foreground" : "font-medium"}>Live</span>
          <Switch checked={simMode} disabled={!isAdmin || setMode.isPending} onCheckedChange={(v) => setMode.mutate(v ? "simulation" : "live")} aria-label="Simulation mode" />
          <span className={simMode ? "font-medium" : "text-muted-foreground"}>Simulation</span>
        </label>
      </div>

      {!simMode ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            This building is in <b>Live</b> mode. {isAdmin ? "Switch to Simulation to run drills with virtual occupants." : "Ask a society admin to switch it to Simulation mode."}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[20rem_1fr]">
            <Card>
              <CardHeader>
                <CardTitle>Scenario</CardTitle>
                <CardDescription>{s ? `t = ${formatDuration(s.t)} · ${s.running ? "running" : "paused"} · ${s.speed}×` : "Not started"}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <Field label={`Occupants (${occupants})`}>
                  <input type="range" min={5} max={400} step={5} value={occupants} onChange={(e) => setOccupants(Number(e.target.value))} aria-label="Occupants" />
                </Field>
                <Field label={`Virtual phones running real positioning (${phoneShare}%)`} hint="These send synthetic Wi-Fi scans through the particle filter.">
                  <input type="range" min={0} max={50} step={5} value={phoneShare} onChange={(e) => setPhoneShare(Number(e.target.value))} aria-label="Phone share" />
                </Field>
                <Field label={`Fire spread (${spread}/min per passage)`}>
                  <input
                    type="range"
                    min={0}
                    max={3}
                    step={0.1}
                    value={spread}
                    onChange={(e) => {
                      setSpread(Number(e.target.value));
                      if (s) sim.mutate({ action: "spread", spread_per_min: Number(e.target.value) });
                    }}
                    aria-label="Fire spread"
                  />
                </Field>
                <div className="grid grid-cols-2 gap-2">
                  <Button onClick={() => sim.mutate({ action: "start", occupants, phone_share: phoneShare / 100, spread_per_min: spread })}>
                    <Users /> {s ? "Restart" : "Start"}
                  </Button>
                  <Button variant="outline" onClick={() => sim.mutate({ action: "spawn", occupants: 20, phone_share: phoneShare / 100 })} disabled={!s}>
                    +20 people
                  </Button>
                  {s?.running ? (
                    <Button variant="secondary" onClick={() => sim.mutate({ action: "pause" })}>
                      <Pause /> Pause
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={() => sim.mutate({ action: "resume" })} disabled={!s}>
                      <Play /> Resume
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => sim.mutate({ action: "reset" })} disabled={!s}>
                    <RotateCcw /> Reset
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {[0.5, 1, 2, 5].map((sp) => (
                    <Button key={sp} size="sm" variant={s?.speed === sp ? "default" : "outline"} onClick={() => sim.mutate({ action: "speed", speed: sp })} disabled={!s}>
                      {sp}×
                    </Button>
                  ))}
                </div>
                <label className="flex items-center justify-between gap-2 rounded-md border p-2 text-sm">
                  <span className="flex items-center gap-1.5">
                    <Flame className="size-4 text-fire" /> Click map to ignite
                  </span>
                  <Switch checked={igniteMode} onCheckedChange={setIgniteMode} aria-label="Click to ignite" />
                </label>
                <Button variant="outline" onClick={() => sim.mutate({ action: "alarm" })} disabled={!s || s.alarm_t != null}>
                  Sound alarm without fire
                </Button>
                <Button variant="ghost" className="text-fire" onClick={() => sim.mutate({ action: "stop" })} disabled={!s}>
                  <Square /> Stop & clear simulated fire
                </Button>
                {s && (
                  <div className="rounded-md bg-muted/50 p-2 text-xs">
                    <p>
                      Evacuated <b>{s.summary.evacuated}</b> / {s.summary.occupants} · trapped <b className="text-fire">{s.summary.trapped}</b> · refuge {s.summary.in_refuge}
                    </p>
                    <p>
                      Avg evac {formatDuration(s.summary.avg_evac_time_s)} · peak exit queue {s.summary.peak_exit_queue}
                    </p>
                    <p>Reroutes: {Object.entries(s.summary.reroutes).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
                    {s.localization_median_error_m != null && <p>Virtual-phone localization error (median): {s.localization_median_error_m} m</p>}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="min-w-0">
              <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
                <CardTitle>{igniteMode ? "Click a room or corridor to start a fire there" : "Click a burning room to extinguish it"}</CardTitle>
                <FloorTabs floors={graph.floors} value={floor.id} onChange={setFloorId} snapshot={snapshot} nodeFloor={nodeFloor} />
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <div className="aspect-[16/10]">
                  <FloorMap
                    graph={graph}
                    floor={floor}
                    hazards={snapshot?.hazards}
                    congestion={snapshot?.congestion}
                    predicted={snapshot?.predicted_congestion}
                    devices={snapshot?.devices}
                    exits={snapshot?.exits}
                    showLabels={false}
                    congestionThreshold={building.settings.congestion_threshold}
                    onNodeClick={(n) => {
                      const burning = snapshot?.hazards[String(n.id)] === "fire";
                      if (!igniteMode || burning) sim.mutate({ action: "extinguish", node_id: n.id });
                      else sim.mutate({ action: "ignite", node_id: n.id });
                    }}
                  />
                </div>
                <MapLegend />
              </CardContent>
            </Card>
          </div>
          {snapshot && <KpiRow kpis={snapshot.kpis} threshold={building.settings.congestion_threshold} />}
        </>
      )}

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-1.5">
              <BarChart3 className="size-4" /> Static plan vs proposed system (paper Table I)
            </CardTitle>
            <CardDescription>
              Runs 5 seeded scenarios twice - nearest-exit static plan vs dynamic A* - with {benchOccupants} people, fire at the currently burning rooms (or a central room).
            </CardDescription>
          </div>
          <Button onClick={() => runBench.mutate()} disabled={!!benchJob || runBench.isPending}>
            {benchJob ? <Loader2 className="animate-spin" /> : <BarChart3 />} {benchJob ? "Running…" : "Run benchmark"}
          </Button>
        </CardHeader>
        <CardContent>
          {bench ? (
            <Table>
              <THead>
                <TR>
                  <TH>Metric</TH>
                  <TH>Static plan</TH>
                  <TH>Proposed (dynamic A*)</TH>
                </TR>
              </THead>
              <TBody>
                {BENCH_ROWS.map(([k, label]) => (
                  <TR key={k}>
                    <TD>{label}</TD>
                    <TD className="tabular-nums">{bench.table[k]?.static ?? "–"}</TD>
                    <TD className="font-medium tabular-nums">{bench.table[k]?.dynamic ?? "–"}</TD>
                  </TR>
                ))}
                <TR>
                  <TD>Evacuation time reduction</TD>
                  <TD>–</TD>
                  <TD>
                    <Badge variant={(bench.evac_time_reduction_pct ?? 0) > 0 ? "safe" : "muted"}>{bench.evac_time_reduction_pct ?? "–"}%</Badge>
                  </TD>
                </TR>
                <TR>
                  <TD>Exit queue reduction</TD>
                  <TD>–</TD>
                  <TD>
                    <Badge variant={(bench.exit_queue_reduction_pct ?? 0) > 0 ? "safe" : "muted"}>{bench.exit_queue_reduction_pct ?? "–"}%</Badge>
                  </TD>
                </TR>
                <TR>
                  <TD>Route recomputation for 200 people</TD>
                  <TD>N/A</TD>
                  <TD className="tabular-nums">{bench.replan_latency_ms_200_people} ms</TD>
                </TR>
                {bench.positioning && (
                  <TR>
                    <TD>Localization error (fused particle filter, median / p90)</TD>
                    <TD>–</TD>
                    <TD className="tabular-nums">
                      {bench.positioning.particle_filter_fused.median_m} m / {bench.positioning.particle_filter_fused.p90_m} m
                      <span className="block text-[11px] text-muted-foreground">
                        trilateration only {bench.positioning.trilateration.median_m} m · fingerprint only {bench.positioning.fingerprint_knn.median_m} m · synthetic scans
                      </span>
                    </TD>
                  </TR>
                )}
              </TBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">{benchJob ? "Simulating… this takes 10–40 seconds." : "No results yet."}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
