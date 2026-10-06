"use client";

import { Download, Pause, Play } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { FloorMap, MapLegend } from "@/components/floor-map";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { FloorTabs } from "@/features/live/floor-tabs";
import { useGraph, useIncident, useIncidentEvents } from "@/lib/hooks";
import type { EventLogItem, LiveDevice } from "@/lib/types";
import { formatDuration } from "@/lib/utils";

type Frame = {
  t: number;
  hazards: Record<string, "risk" | "smoke" | "fire">;
  devices: LiveDevice[];
  kpis: Record<string, number>;
  exits: { node_id: number; assigned: number; queue: number }[];
};

const EVENT_LABEL: Record<string, string> = {
  "incident.opened": "Incident opened",
  "incident.status": "Status changed",
  "notification.sent": "Residents alerted",
  "sensor.triggered": "Sensor alarm",
  "hazard.updated": "Hazard updated",
  "route.assigned": "Route assigned",
  "route.none": "No safe route",
  "participant.status": "Resident status",
  "sos.created": "SOS",
  "sos.resolved": "SOS resolved",
};

function toFrames(items: EventLogItem[], start: number): Frame[] {
  return items
    .filter((e) => e.type === "snapshot")
    .map((e) => {
      const p = e.payload as { hazards: Frame["hazards"]; kpis: Frame["kpis"]; exits: Frame["exits"]; devices: [string, string, number, number, number, string, number | null][] };
      return {
        t: (Date.parse(e.ts) - start) / 1000,
        hazards: p.hazards ?? {},
        kpis: p.kpis ?? {},
        exits: p.exits ?? [],
        devices: (p.devices ?? []).map(([id, k, x, y, level, status, goal]) => ({
          id,
          kind: k === "r" ? "real" : "virtual",
          name: id,
          x,
          y,
          level,
          status,
          goal,
          node_id: null,
          source: "",
          confidence: 1,
          stairs_ok: true,
          route: [],
          goal_type: null,
          remaining_m: null,
          progress: null,
        })),
      };
    });
}

export default function ReplayPage() {
  const id = Number(useParams<{ id: string }>().id);
  const { data: incident } = useIncident(id);
  const { data: events } = useIncidentEvents(id);
  const { data: graph } = useGraph(incident?.building_id ?? 0);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [chosenFloor, setFloorId] = useState<number | null>(null);

  const start = incident?.started_at ? Date.parse(incident.started_at) : 0;
  const frames = useMemo(() => (events ? toFrames(events.items, start) : []), [events, start]);
  const timeline = useMemo(() => (events?.items ?? []).filter((e) => e.type !== "snapshot"), [events]);
  const nodes = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);
  const nodeFloor = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n.floor_id])), [graph]);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setIdx((i) => (i + 1 < frames.length ? i + 1 : (setPlaying(false), i))), 500);
    return () => clearInterval(t);
  }, [playing, frames.length]);

  const floorId = chosenFloor ?? (graph ? [...graph.floors].sort((a, b) => a.level - b.level)[0]?.id ?? null : null);

  if (!incident || !graph || !events) return <Skeleton className="h-[70vh]" />;
  const frame = frames[Math.min(idx, frames.length - 1)];
  const floor = graph.floors.find((f) => f.id === floorId) ?? graph.floors[0];
  const m = incident.metrics;
  const visible = timeline.filter((e) => !frame || (Date.parse(e.ts) - start) / 1000 <= frame.t + 1);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">
            Incident #{incident.id} - {incident.kind} {incident.is_simulation && <Badge variant="muted">simulated</Badge>}
          </h1>
          <p className="text-sm text-muted-foreground">
            {incident.started_at && new Date(incident.started_at).toLocaleString()} · {incident.status.replace("_", " ")}
          </p>
        </div>
        <Button asChild variant="outline">
          <a href={`/bff/incidents/${id}/export.csv`}>
            <Download /> Export CSV
          </a>
        </Button>
      </div>

      {m && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
          {[
            ["Duration", formatDuration(m.duration_s)],
            ["Residents", m.residents],
            ["Avg evacuation (residents)", formatDuration(m.avg_evac_time_s)],
            ["Avg alert → acknowledge", formatDuration(m.avg_ack_time_s)],
            ["Route assignments", m.route_assignments],
            ["Route update latency (avg / p95)", m.avg_route_update_latency_ms != null ? `${m.avg_route_update_latency_ms} / ${m.p95_route_update_latency_ms} ms` : "–"],
            ["Reroutes", Object.entries(m.reroutes_by_reason).map(([k, v]) => `${k} ${v}`).join(", ") || "–"],
          ].map(([label, value]) => (
            <Card key={String(label)} className="p-3">
              <p className="text-[11px] text-muted-foreground">{label}</p>
              <p className="text-sm font-semibold tabular-nums">{value}</p>
            </Card>
          ))}
        </div>
      )}

      {m?.simulation && (
        <Card className="p-3 text-sm">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Simulated occupants</p>
          {(() => {
            const sim = m.simulation as Record<string, unknown>;
            const reroutes = (sim.reroutes ?? {}) as Record<string, number>;
            return (
              <p className="tabular-nums">
                {String(sim.evacuated)} / {String(sim.occupants)} evacuated · {String(sim.trapped)} trapped · {String(sim.in_refuge)} in refuge · avg{" "}
                {formatDuration(sim.avg_evac_time_s as number)} · p90 {formatDuration(sim.p90_evac_time_s as number)} · peak exit queue {String(sim.peak_exit_queue)} · reroutes{" "}
                {Object.entries(reroutes).map(([k, v]) => `${k} ${v}`).join(", ")}
                {sim.localization_median_error_m != null && ` · virtual-phone localization ${String(sim.localization_median_error_m)} m median`}
              </p>
            );
          })()}
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <Card className="min-w-0">
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>Replay {frame ? `· t = ${formatDuration(frame.t)}` : ""}</CardTitle>
            <FloorTabs floors={graph.floors} value={floor.id} onChange={setFloorId} nodeFloor={nodeFloor} />
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {frames.length ? (
              <>
                <div className="aspect-[16/10]">
                  <FloorMap graph={graph} floor={floor} hazards={frame?.hazards} devices={frame?.devices} showLabels={false} />
                </div>
                <div className="flex items-center gap-3">
                  <Button size="icon" variant="outline" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause" : "Play"}>
                    {playing ? <Pause /> : <Play />}
                  </Button>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, frames.length - 1)}
                    value={idx}
                    onChange={(e) => {
                      setPlaying(false);
                      setIdx(Number(e.target.value));
                    }}
                    className="flex-1"
                    aria-label="Replay position"
                  />
                  <span className="w-28 text-right text-xs tabular-nums text-muted-foreground">
                    {frame && `${frame.kpis.evacuated ?? 0} safe · ${frame.kpis.fire_alerts ?? 0} fires`}
                  </span>
                </div>
                <MapLegend />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No replay frames were recorded for this incident.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Event log</CardTitle>
          </CardHeader>
          <CardContent className="flex max-h-[32rem] flex-col gap-1 overflow-y-auto text-xs">
            {visible
              .slice(-200)
              .reverse()
              .map((e) => {
                const p = e.payload as Record<string, unknown>;
                return (
                  <div key={e.id} className="border-b py-1 last:border-0">
                    <span className="tabular-nums text-muted-foreground">{formatDuration((Date.parse(e.ts) - start) / 1000)}</span>{" "}
                    <span className="font-medium">{EVENT_LABEL[e.type] ?? e.type}</span>{" "}
                    <span className="text-muted-foreground">
                      {typeof p.reason === "string" && `(${p.reason}) `}
                      {typeof p.status === "string" && p.status}
                      {typeof p.node_id === "number" && nodes.get(p.node_id)?.name}
                      {typeof p.goal === "number" && ` → ${nodes.get(p.goal)?.name}`}
                      {typeof p.latency_ms === "number" && ` · ${p.latency_ms} ms`}
                      {Array.isArray(p.reasons) && (p.reasons as string[]).join(", ")}
                    </span>
                  </div>
                );
              })}
          </CardContent>
        </Card>
      </div>

      {incident.participants.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Residents</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Flat</TH>
                  <TH>Status</TH>
                  <TH>Alerted</TH>
                  <TH>Acknowledged</TH>
                  <TH>Safe at</TH>
                  <TH>Assigned exit</TH>
                </TR>
              </THead>
              <TBody>
                {incident.participants.map((p) => (
                  <TR key={p.device_id}>
                    <TD>{p.name ?? p.device_id.slice(0, 8)}</TD>
                    <TD>{p.flat ?? "–"}</TD>
                    <TD>
                      <Badge variant={p.status === "safe" ? "safe" : p.status === "needs_help" ? "fire" : "muted"}>{p.status.replace("_", " ")}</Badge>
                    </TD>
                    {[p.notified_at, p.acknowledged_at, p.safe_at].map((t, i) => (
                      <TD key={i} className="text-xs tabular-nums">
                        {t && incident.started_at ? `+${formatDuration((Date.parse(t) - Date.parse(incident.started_at)) / 1000)}` : "–"}
                      </TD>
                    ))}
                    <TD className="text-xs">{p.assigned_exit_id != null ? nodes.get(p.assigned_exit_id)?.name : "–"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
