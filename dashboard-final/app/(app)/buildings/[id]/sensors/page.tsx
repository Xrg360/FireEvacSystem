"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Field, Input, Select, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import { API_PUBLIC_URL } from "@/lib/realtime/socket-provider";
import { useBuilding, useGraph, useMe, useSensorReadings, useSensors } from "@/lib/hooks";
import type { Sensor } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

function KeyReveal({ sensor, apiKey }: { sensor: Sensor; apiKey: string }) {
  const curl = `curl -X POST ${API_PUBLIC_URL}/api/sensors/${sensor.id}/readings -H "X-Sensor-Key: ${apiKey}" -H "Content-Type: application/json" -d '{"smoke": 120, "temperature_c": 31}'`;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-risk bg-risk/10 p-3 text-xs">
      <p className="font-medium">API key for “{sensor.name}” - copy it now, it is not shown again.</p>
      <code className="break-all rounded bg-background px-2 py-1">{apiKey}</code>
      <p className="text-muted-foreground">ESP32 / test request:</p>
      <code className="break-all rounded bg-background px-2 py-1">{curl}</code>
      <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(apiKey).then(() => toast.success("Copied"))}>
        <Copy /> Copy key
      </Button>
    </div>
  );
}

function Readings({ sensorId }: { sensorId: number }) {
  const { data } = useSensorReadings(sensorId);
  const rows = useMemo(() => (data ?? []).map((r) => ({ t: new Date(r.ts).toLocaleTimeString(), smoke: r.smoke, temp: r.temperature_c })), [data]);
  if (!data) return <Skeleton className="h-40" />;
  if (!rows.length) return <p className="text-xs text-muted-foreground">No readings received yet.</p>;
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
          <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={40} />
          <YAxis yAxisId="l" tick={{ fontSize: 10 }} />
          <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", fontSize: 12 }} />
          <Line yAxisId="l" type="monotone" dataKey="smoke" name="Smoke" stroke="var(--smoke)" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line yAxisId="r" type="monotone" dataKey="temp" name="Temp °C" stroke="var(--fire)" dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function SensorsPage() {
  const id = Number(useParams<{ id: string }>().id);
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: building } = useBuilding(id);
  const { data: graph } = useGraph(id, building?.graph_version);
  const { data: sensors, isLoading } = useSensors(id);
  const [selected, setSelected] = useState<number | null>(null);
  const [revealed, setRevealed] = useState<{ sensor: Sensor; key: string } | null>(null);
  const [form, setForm] = useState({ name: "", type: "multi", node_id: "" });
  const [open, setOpen] = useState(false);
  const isAdmin = me?.user.role === "society_admin";
  const rooms = (graph?.nodes ?? []).filter((n) => n.type !== "assembly");

  const create = useMutation({
    mutationFn: () => api.post<Sensor>(`/buildings/${id}/sensors`, { ...form, node_id: Number(form.node_id) }),
    onSuccess: (s) => {
      setRevealed({ sensor: s, key: s.api_key! });
      setOpen(false);
      setForm({ name: "", type: "multi", node_id: "" });
      qc.invalidateQueries({ queryKey: ["sensors", id] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const rotate = useMutation({
    mutationFn: (s: Sensor) => api.post<{ api_key: string }>(`/sensors/${s.id}/rotate-key`).then((r) => ({ s, key: r.api_key })),
    onSuccess: ({ s, key }) => setRevealed({ sensor: s, key }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (s: Sensor) => api.del(`/sensors/${s.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sensors", id] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const clearHazards = useMutation({
    mutationFn: () => api.del(`/buildings/${id}/hazards`),
    onSuccess: (r: unknown) => {
      toast.success(`Cleared ${(r as { cleared: number }).cleared} hazards and reset sensor alarms`);
      qc.invalidateQueries({ queryKey: ["sensors", id] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Fire sensors</h1>
          <p className="text-sm text-muted-foreground">
            Smoke ≥ {building?.settings.smoke_threshold}, temperature ≥ {building?.settings.temp_threshold_c} °C, a rise of ≥ {building?.settings.rate_of_rise_c_per_min} °C/min, a flame sensor or an alarm-panel contact marks the room on fire and alerts residents.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => clearHazards.mutate()}>
            Clear all hazards
          </Button>
          {isAdmin && (
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button>
                  <Plus /> Add sensor
                </Button>
              </DialogTrigger>
              <DialogContent title="Register a sensor" description="You will get an API key for the device.">
                <div className="flex flex-col gap-3">
                  <Field label="Name">
                    <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Flat 304 kitchen detector" />
                  </Field>
                  <Field label="Type">
                    <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                      <option value="multi">Smoke + temperature (e.g. MQ-2 + DHT22)</option>
                      <option value="smoke">Smoke only</option>
                      <option value="temperature">Temperature only</option>
                      <option value="flame">Flame sensor</option>
                      <option value="alarm_panel">Fire alarm panel relay (dry contact)</option>
                    </Select>
                  </Field>
                  <Field label="Location">
                    <Select value={form.node_id} onChange={(e) => setForm({ ...form, node_id: e.target.value })}>
                      <option value="">Choose a room…</option>
                      {graph?.floors.map((f) => (
                        <optgroup key={f.id} label={f.name}>
                          {rooms
                            .filter((n) => n.floor_id === f.id)
                            .map((n) => (
                              <option key={n.id} value={n.id}>
                                {n.name}
                              </option>
                            ))}
                        </optgroup>
                      ))}
                    </Select>
                  </Field>
                  <Button onClick={() => create.mutate()} disabled={!form.name || !form.node_id || create.isPending}>
                    Register
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>

      {revealed && <KeyReveal sensor={revealed.sensor} apiKey={revealed.key} />}

      <div className="grid gap-4 xl:grid-cols-[1fr_26rem]">
        <Card>
          <CardContent className="pt-4">
            {isLoading && <Skeleton className="h-40" />}
            {sensors && !sensors.length && <EmptyState title="No sensors registered" />}
            {sensors && sensors.length > 0 && (
              <Table>
                <THead>
                  <TR>
                    <TH>Sensor</TH>
                    <TH>Location</TH>
                    <TH>Last reading</TH>
                    <TH>Seen</TH>
                    <TH>State</TH>
                    {isAdmin && <TH />}
                  </TR>
                </THead>
                <TBody>
                  {sensors.map((s) => (
                    <TR key={s.id} onClick={() => setSelected(s.id)} className={selected === s.id ? "cursor-pointer bg-accent" : "cursor-pointer"}>
                      <TD>
                        <p className="font-medium">{s.name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          #{s.id} · {s.type.replace("_", " ")}
                        </p>
                      </TD>
                      <TD className="text-xs">{s.node_name}</TD>
                      <TD className="text-xs tabular-nums">
                        {s.last_reading
                          ? [
                              s.last_reading.smoke != null && `smoke ${s.last_reading.smoke}`,
                              s.last_reading.temperature_c != null && `${s.last_reading.temperature_c} °C`,
                              s.last_reading.flame && "flame",
                              s.last_reading.alarm && "alarm",
                            ]
                              .filter(Boolean)
                              .join(" · ")
                          : "–"}
                      </TD>
                      <TD className="text-xs">{timeAgo(s.last_seen)}</TD>
                      <TD>{s.triggered ? <Badge variant="fire">ALARM</Badge> : <Badge variant="safe">normal</Badge>}</TD>
                      {isAdmin && (
                        <TD className="whitespace-nowrap">
                          <Button size="icon" variant="ghost" aria-label="Rotate key" onClick={(e) => { e.stopPropagation(); rotate.mutate(s); }}>
                            <KeyRound />
                          </Button>
                          <Button size="icon" variant="ghost" aria-label="Delete sensor" onClick={(e) => { e.stopPropagation(); if (confirm(`Delete ${s.name}?`)) remove.mutate(s); }}>
                            <Trash2 />
                          </Button>
                        </TD>
                      )}
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Readings</CardTitle>
            <CardDescription>{selected ? sensors?.find((s) => s.id === selected)?.name : "Select a sensor"}</CardDescription>
          </CardHeader>
          <CardContent>{selected ? <Readings sensorId={selected} /> : <p className="text-xs text-muted-foreground">Click a sensor to see its last 120 readings.</p>}</CardContent>
        </Card>
      </div>
    </div>
  );
}
