"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Link2, MousePointer2, Move, Plus, Radio, Trash2, Upload, Wifi } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { FloorMap } from "@/components/floor-map";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, Select, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import { useBuilding, useGraph, useMe } from "@/lib/hooks";
import type { AccessPoint, EdgeKind, Graph, GraphNode, NodeType } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tool = "select" | "add" | "connect" | "move" | "ap";
type Sel = { kind: "node"; id: number } | { kind: "edge"; index: number } | { kind: "ap"; bssid: string } | null;

const NODE_TYPES: NodeType[] = ["room", "corridor", "stair", "lift", "exit", "refuge", "assembly"];
const EDGE_KINDS: EdgeKind[] = ["corridor", "door", "stair", "lift", "outdoor"];

let tempId = -1;
const nextTemp = () => tempId--;

export default function EditorPage() {
  const id = Number(useParams<{ id: string }>().id);
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: building } = useBuilding(id);
  const { data: published } = useGraph(id, building?.graph_version);
  // local copy exists only while there are unpublished edits; otherwise show the published graph
  const [local, setLocal] = useState<Graph | null>(null);
  const draft = local ?? published ?? null;
  const dirty = local != null;
  const [chosenFloor, setFloorId] = useState<number | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [newType, setNewType] = useState<NodeType>("room");
  const [sel, setSel] = useState<Sel>(null);
  const [connectFrom, setConnectFrom] = useState<number | null>(null);
  const [problems, setProblems] = useState<string[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const planRef = useRef<HTMLInputElement>(null);

  const floorId = chosenFloor ?? (draft ? [...draft.floors].sort((a, b) => a.level - b.level)[0]?.id ?? null : null);

  const coverage = useQuery({
    queryKey: ["coverage", id],
    queryFn: () => api.get<{ nodes: { node_id: number; samples: number }[]; recommended_per_node: number }>(`/buildings/${id}/survey/coverage`),
  });
  const samples = useMemo(() => new Map((coverage.data?.nodes ?? []).map((n) => [n.node_id, n.samples])), [coverage.data]);

  const publish = useMutation({
    mutationFn: () => api.put<Graph>(`/buildings/${id}/graph`, draft as unknown as Record<string, unknown>),
    onSuccess: (g) => {
      toast.success(`Published graph v${g.building.graph_version}`);
      setLocal(null);
      setProblems(null);
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["graph", id] });
    },
    onError: (e) => {
      const detail = (e as { detail?: { problems?: string[] } }).detail;
      if (detail?.problems) setProblems(detail.problems);
      toast.error(errorMessage(e));
    },
  });
  const validate = useMutation({
    mutationFn: () => api.post<{ ok: boolean; problems: string[] }>(`/buildings/${id}/graph/validate`, draft as unknown as Record<string, unknown>),
    onSuccess: (r) => setProblems(r.problems),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const calibrate = useMutation({
    mutationFn: () =>
      api.post<{ access_points: { bssid: string; samples: number; calibrated: boolean; p_ref: number; eta: number }[]; fingerprint_cross_validation: { accuracy: number | null; mean_error_m: number | null; samples: number } }>(
        `/buildings/${id}/survey/calibrate`,
      ),
    onSuccess: (r) => {
      const cv = r.fingerprint_cross_validation;
      const n = r.access_points.filter((a) => a.calibrated).length;
      toast.success(`Calibrated ${n}/${r.access_points.length} routers`, {
        description: cv.accuracy != null ? `Fingerprint accuracy ${(cv.accuracy * 100).toFixed(0)}% (room), mean error ${cv.mean_error_m?.toFixed(1)} m over ${cv.samples} scans` : "Not enough survey scans for cross-validation yet",
        duration: 12000,
      });
      qc.invalidateQueries({ queryKey: ["graph", id] });
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (me && me.user.role !== "society_admin") return <p className="text-sm text-muted-foreground">Only society admins can edit floor plans.</p>;
  if (!draft || !building) return <Skeleton className="h-[70vh]" />;
  const floor = draft.floors.find((f) => f.id === floorId) ?? draft.floors[0];

  const update = (fn: (g: Graph) => void) => {
    setLocal((g) => {
      const next = structuredClone(g ?? published!);
      fn(next);
      return next;
    });
    setProblems(null);
  };

  const selNode = sel?.kind === "node" ? draft.nodes.find((n) => n.id === sel.id) : undefined;
  const selEdge = sel?.kind === "edge" ? draft.edges[sel.index] : undefined;
  const selAp = sel?.kind === "ap" ? draft.access_points.find((a) => a.bssid === sel.bssid) : undefined;

  function onBackground(x: number, y: number) {
    if (tool === "add" && floor) {
      const nid = nextTemp();
      const count = draft!.nodes.filter((n) => n.type === newType).length + 1;
      update((g) =>
        g.nodes.push({
          id: nid,
          key: `${newType.toUpperCase()}-${Date.now().toString(36).slice(-4)}`,
          name: `${newType[0].toUpperCase()}${newType.slice(1)} ${count}`,
          type: newType,
          floor_id: floor.id,
          x,
          y,
          capacity: newType === "corridor" ? 15 : newType === "room" ? 6 : 10,
          exit_flow_per_min: newType === "exit" ? 40 : null,
          lat: null,
          lng: null,
        }),
      );
      setSel({ kind: "node", id: nid });
    } else if (tool === "move" && selNode) {
      update((g) => {
        const n = g.nodes.find((m) => m.id === selNode.id)!;
        n.x = x;
        n.y = y;
      });
    } else if (tool === "ap" && floor) {
      const bssid = prompt("Router BSSID (MAC address, e.g. a4:2b:b0:12:34:56)")?.trim().toLowerCase();
      if (!bssid || !/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(bssid)) return bssid && toast.error("Not a valid BSSID");
      update((g) => g.access_points.push({ bssid, ssid: null, floor_id: floor.id, x, y, p_ref: -40, eta: 2.7 }));
      setSel({ kind: "ap", bssid });
    } else {
      setSel(null);
    }
  }

  function onNode(n: GraphNode) {
    if (tool === "connect") {
      if (connectFrom == null) {
        setConnectFrom(n.id);
        return;
      }
      if (connectFrom !== n.id && !draft!.edges.some((e) => (e.a === connectFrom && e.b === n.id) || (e.b === connectFrom && e.a === n.id))) {
        const a = draft!.nodes.find((m) => m.id === connectFrom)!;
        const vertical = a.floor_id !== n.floor_id;
        const kind: EdgeKind = vertical ? (a.type === "lift" ? "lift" : "stair") : a.type === "room" || n.type === "room" ? "door" : "corridor";
        update((g) => g.edges.push({ a: connectFrom, b: n.id, kind, length_m: vertical ? 8 : null, width_m: 1.2, accessible: kind !== "stair" }));
        setSel({ kind: "edge", index: draft!.edges.length });
      }
      setConnectFrom(null);
      return;
    }
    setSel({ kind: "node", id: n.id });
  }

  function deleteSelected() {
    if (!sel) return;
    update((g) => {
      if (sel.kind === "node") {
        g.nodes = g.nodes.filter((n) => n.id !== sel.id);
        g.edges = g.edges.filter((e) => e.a !== sel.id && e.b !== sel.id);
      } else if (sel.kind === "edge") g.edges.splice(sel.index, 1);
      else g.access_points = g.access_points.filter((a) => a.bssid !== sel.bssid);
    });
    setSel(null);
  }

  const floorEdges = draft.edges
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => [e.a, e.b].some((nid) => draft.nodes.find((n) => n.id === nid)?.floor_id === floor?.id));

  async function uploadPlan(file: File) {
    if (!floor || floor.id < 0) return toast.error("Publish the new floor first, then upload its plan");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post<{ plan_image: string }>(`/floors/${floor.id}/plan`, fd);
      update((g) => {
        g.floors.find((f) => f.id === floor.id)!.plan_image = r.plan_image;
      });
      toast.success("Floor plan uploaded");
      qc.invalidateQueries({ queryKey: ["buildings"] });
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  const tools: [Tool, string, typeof Plus][] = [
    ["select", "Select", MousePointer2],
    ["add", "Add node", Plus],
    ["connect", "Connect", Link2],
    ["move", "Move selected", Move],
    ["ap", "Add router", Wifi],
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Floor plan editor - {building.name}</h1>
          <p className="text-sm text-muted-foreground">Coordinates are in metres. Publishing bumps the graph version; phones re-download it for offline routing.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            hidden
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                const g = JSON.parse(await f.text()) as Graph;
                if (!Array.isArray(g.nodes) || !Array.isArray(g.edges) || !Array.isArray(g.floors)) throw new Error("Not a graph file");
                setLocal({ ...g, access_points: g.access_points ?? [] });
                setFloorId(g.floors[0]?.id ?? null);
                toast.success("Imported - review and publish");
              } catch (err) {
                toast.error(errorMessage(err));
              }
              e.target.value = "";
            }}
          />
          <Button variant="outline" onClick={() => fileRef.current?.click()}>
            <Upload /> Import JSON
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = `${building.name.replace(/\W+/g, "_")}_graph.json`;
              a.click();
            }}
          >
            <Download /> Export
          </Button>
          <Button variant="outline" onClick={() => validate.mutate()}>
            Validate
          </Button>
          {dirty && (
            <Button
              variant="ghost"
              onClick={() => setLocal(null)}
            >
              Discard
            </Button>
          )}
          <Button onClick={() => publish.mutate()} disabled={!dirty || publish.isPending}>
            <CheckCircle2 /> Publish
          </Button>
        </div>
      </div>

      {problems && (
        <div className={cn("rounded-lg border p-3 text-sm", problems.length ? "border-fire bg-fire/5" : "border-safe bg-safe/10")}>
          {problems.length ? (
            <ul className="list-disc pl-5">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : (
            "Graph is valid: every space can reach an exit and every floor is connected."
          )}
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-[1fr_20rem]">
        <Card className="min-w-0">
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1" role="toolbar" aria-label="Editor tools">
              {tools.map(([t, label, Icon]) => (
                <Button key={t} size="sm" variant={tool === t ? "default" : "outline"} onClick={() => { setTool(t); setConnectFrom(null); }}>
                  <Icon /> {label}
                </Button>
              ))}
              {tool === "add" && (
                <Select value={newType} onChange={(e) => setNewType(e.target.value as NodeType)} className="h-8 w-32 text-xs" aria-label="Node type">
                  {NODE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </Select>
              )}
            </div>
            <div className="flex flex-wrap gap-1">
              {[...draft.floors].sort((a, b) => b.level - a.level).map((f) => (
                <Button key={f.id} size="sm" variant={f.id === floor?.id ? "secondary" : "ghost"} onClick={() => setFloorId(f.id)}>
                  {f.name}
                </Button>
              ))}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const fid = nextTemp();
                  const level = Math.max(...draft.floors.map((f) => f.level), -1) + 1;
                  update((g) => g.floors.push({ id: fid, level, name: `Floor ${level}`, width_m: floor?.width_m ?? 30, height_m: floor?.height_m ?? 20 }));
                  setFloorId(fid);
                }}
              >
                <Plus /> Floor
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <p className="mb-2 text-xs text-muted-foreground">
              {tool === "add" && `Click the plan to place a ${newType}.`}
              {tool === "connect" && (connectFrom == null ? "Click the first node of a passage." : "Now click the node it connects to (can be on another floor - switch floors first).")}
              {tool === "move" && (selNode ? `Click where ${selNode.name} should go.` : "Select a node first (Select tool), then click its new position.")}
              {tool === "ap" && "Click where a Wi-Fi router is mounted."}
              {tool === "select" && "Click a node, router or passage to edit it. Numbers on nodes are survey scans recorded there."}
            </p>
            {floor && (
              <div className="aspect-[16/10]">
                <FloorMap
                  graph={draft}
                  floor={floor}
                  showAccessPoints
                  selectedNode={selNode?.id ?? connectFrom}
                  onBackgroundClick={onBackground}
                  onNodeClick={onNode}
                  onAccessPointClick={(ap) => setSel({ kind: "ap", bssid: ap.bssid })}
                  overlay={
                    <>
                      {draft.nodes
                        .filter((n) => n.floor_id === floor.id && n.type !== "assembly")
                        .map((n) => {
                          const c = samples.get(n.id) ?? 0;
                          return (
                            <text key={`s${n.id}`} x={n.x - 1.6} y={n.y - 1} fontSize={0.65} fill={c >= (coverage.data?.recommended_per_node ?? 20) ? "var(--safe)" : c ? "var(--smoke)" : "var(--muted-foreground)"} pointerEvents="none">
                              {c}
                            </text>
                          );
                        })}
                      {floorEdges.map(({ e, i }) => {
                        const a = draft.nodes.find((n) => n.id === e.a)!;
                        const b = draft.nodes.find((n) => n.id === e.b)!;
                        if (a.floor_id !== b.floor_id) return null;
                        return (
                          <line
                            key={`hit${i}`}
                            x1={a.x}
                            y1={a.y}
                            x2={b.x}
                            y2={b.y}
                            stroke={sel?.kind === "edge" && sel.index === i ? "var(--primary)" : "transparent"}
                            strokeWidth={0.9}
                            className="cursor-pointer"
                            onClick={(ev) => {
                              ev.stopPropagation();
                              setSel({ kind: "edge", index: i });
                            }}
                          />
                        );
                      })}
                    </>
                  }
                />
              </div>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-3">
          {selNode && (
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle>Node</CardTitle>
                <Button size="icon" variant="ghost" onClick={deleteSelected} aria-label="Delete node">
                  <Trash2 />
                </Button>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <div className="col-span-2">
                  <Field label="Name">
                    <Input value={selNode.name} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.name = e.target.value; })} />
                  </Field>
                </div>
                <Field label="Key (unique)">
                  <Input value={selNode.key} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.key = e.target.value; })} />
                </Field>
                <Field label="Type">
                  <Select value={selNode.type} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.type = e.target.value as NodeType; })}>
                    {NODE_TYPES.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="x (m)">
                  <Input type="number" step="0.1" value={selNode.x} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.x = Number(e.target.value); })} />
                </Field>
                <Field label="y (m)">
                  <Input type="number" step="0.1" value={selNode.y} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.y = Number(e.target.value); })} />
                </Field>
                <Field label="Capacity (people)">
                  <Input type="number" min={1} value={selNode.capacity} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.capacity = Number(e.target.value); })} />
                </Field>
                {selNode.type === "exit" && (
                  <Field label="Exit flow (people/min)">
                    <Input type="number" min={1} value={selNode.exit_flow_per_min ?? 40} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.exit_flow_per_min = Number(e.target.value); })} />
                  </Field>
                )}
                {(selNode.type === "assembly" || selNode.type === "exit") && (
                  <>
                    <Field label="Latitude" hint="for the GPS 'are you safe?' check">
                      <Input type="number" step="0.000001" value={selNode.lat ?? ""} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.lat = e.target.value ? Number(e.target.value) : null; })} />
                    </Field>
                    <Field label="Longitude">
                      <Input type="number" step="0.000001" value={selNode.lng ?? ""} onChange={(e) => update((g) => { g.nodes.find((n) => n.id === selNode.id)!.lng = e.target.value ? Number(e.target.value) : null; })} />
                    </Field>
                  </>
                )}
                <p className="col-span-2 text-[11px] text-muted-foreground">
                  Survey scans here: <b>{samples.get(selNode.id) ?? 0}</b> (aim for {coverage.data?.recommended_per_node ?? 20})
                </p>
              </CardContent>
            </Card>
          )}
          {selEdge && (
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle>Passage</CardTitle>
                <Button size="icon" variant="ghost" onClick={deleteSelected} aria-label="Delete passage">
                  <Trash2 />
                </Button>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <p className="col-span-2 text-xs text-muted-foreground">
                  {draft.nodes.find((n) => n.id === selEdge.a)?.name} ↔ {draft.nodes.find((n) => n.id === selEdge.b)?.name}
                </p>
                <Field label="Kind">
                  <Select value={selEdge.kind} onChange={(e) => update((g) => { g.edges[(sel as { index: number }).index].kind = e.target.value as EdgeKind; })}>
                    {EDGE_KINDS.map((k) => (
                      <option key={k}>{k}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Walking length (m)" hint="blank = straight line">
                  <Input type="number" step="0.1" value={selEdge.length_m ?? ""} onChange={(e) => update((g) => { g.edges[(sel as { index: number }).index].length_m = e.target.value ? Number(e.target.value) : null; })} />
                </Field>
                <Field label="Width (m)">
                  <Input type="number" step="0.1" value={selEdge.width_m} onChange={(e) => update((g) => { g.edges[(sel as { index: number }).index].width_m = Number(e.target.value); })} />
                </Field>
                <label className="flex items-center gap-2 self-end pb-2 text-xs">
                  <input type="checkbox" checked={selEdge.accessible} onChange={(e) => update((g) => { g.edges[(sel as { index: number }).index].accessible = e.target.checked; })} />
                  Wheelchair accessible
                </label>
              </CardContent>
            </Card>
          )}
          {selAp && (
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-1.5">
                  <Radio className="size-4" /> Router {selAp.calibrated && <Badge variant="info">calibrated</Badge>}
                </CardTitle>
                <Button size="icon" variant="ghost" onClick={deleteSelected} aria-label="Delete router">
                  <Trash2 />
                </Button>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <p className="col-span-2 font-mono text-xs">{selAp.bssid}</p>
                {(["ssid", "x", "y", "p_ref", "eta"] as (keyof AccessPoint)[]).map((k) => (
                  <Field key={k} label={k === "p_ref" ? "P_ref (dBm @1 m)" : k === "eta" ? "η path loss" : k}>
                    <Input
                      type={k === "ssid" ? "text" : "number"}
                      step="0.1"
                      value={String(selAp[k] ?? "")}
                      onChange={(e) =>
                        update((g) => {
                          const ap = g.access_points.find((a) => a.bssid === selAp.bssid)! as unknown as Record<string, unknown>;
                          ap[k] = k === "ssid" ? e.target.value : Number(e.target.value);
                        })
                      }
                    />
                  </Field>
                ))}
              </CardContent>
            </Card>
          )}
          {floor && (
            <Card>
              <CardHeader>
                <CardTitle>{floor.name}</CardTitle>
                <CardDescription>Level {floor.level}</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <div className="col-span-2">
                  <Field label="Name">
                    <Input value={floor.name} onChange={(e) => update((g) => { g.floors.find((f) => f.id === floor.id)!.name = e.target.value; })} />
                  </Field>
                </div>
                <Field label="Width (m)">
                  <Input type="number" value={floor.width_m} onChange={(e) => update((g) => { g.floors.find((f) => f.id === floor.id)!.width_m = Number(e.target.value); })} />
                </Field>
                <Field label="Depth (m)">
                  <Input type="number" value={floor.height_m} onChange={(e) => update((g) => { g.floors.find((f) => f.id === floor.id)!.height_m = Number(e.target.value); })} />
                </Field>
                <input ref={planRef} type="file" accept="image/*" hidden onChange={(e) => e.target.files?.[0] && uploadPlan(e.target.files[0])} />
                <Button className="col-span-2" variant="outline" size="sm" onClick={() => planRef.current?.click()}>
                  <Upload /> {floor.plan_image ? "Replace" : "Upload"} floor plan image
                </Button>
                <p className="col-span-2 text-[11px] text-muted-foreground">The image is stretched to the width × depth above - set them to the real size of the drawing.</p>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Wi-Fi calibration</CardTitle>
              <CardDescription>After surveying rooms in the app: fits P_ref and η per router (eq. 1) and checks fingerprint accuracy.</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" className="w-full" onClick={() => calibrate.mutate()} disabled={calibrate.isPending}>
                Calibrate from survey data
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
