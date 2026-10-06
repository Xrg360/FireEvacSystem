"use client";

// Floor plan + evacuation graph renderer (SVG, metre coordinates). Used by the live command
// view, incident replay, the simulation console and the editor.
import { useMemo, type MouseEvent, type ReactNode } from "react";

import { API_PUBLIC_URL } from "@/lib/realtime/socket-provider";
import type { AccessPoint, ExitInfo, Floor, Graph, GraphNode, LiveDevice } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface FloorMapProps {
  graph: Graph;
  floor: Floor;
  hazards?: Record<string, string>;
  congestion?: Record<string, number>;
  predicted?: Record<string, number>;
  devices?: LiveDevice[];
  exits?: ExitInfo[];
  selectedDevice?: string | null;
  selectedNode?: number | null;
  highlightNodes?: number[];
  showLabels?: boolean;
  showAccessPoints?: boolean;
  congestionThreshold?: number;
  onNodeClick?: (node: GraphNode, e: MouseEvent) => void;
  onDeviceClick?: (device: LiveDevice) => void;
  onBackgroundClick?: (x: number, y: number, e: MouseEvent<SVGSVGElement>) => void;
  onAccessPointClick?: (ap: AccessPoint) => void;
  overlay?: ReactNode;
  className?: string;
  sosNodes?: number[];
}

const NODE_R: Record<string, number> = { room: 0.9, corridor: 0.55, stair: 0.8, lift: 0.7, exit: 1.0, refuge: 0.9, assembly: 1.1 };

export function FloorMap({
  graph,
  floor,
  hazards = {},
  congestion = {},
  predicted = {},
  devices = [],
  exits = [],
  selectedDevice,
  selectedNode,
  highlightNodes,
  showLabels = true,
  showAccessPoints = false,
  congestionThreshold = 0.8,
  onNodeClick,
  onDeviceClick,
  onBackgroundClick,
  onAccessPointClick,
  overlay,
  className,
  sosNodes = [],
}: FloorMapProps) {
  const nodes = useMemo(() => graph.nodes.filter((n) => n.floor_id === floor.id), [graph.nodes, floor.id]);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const levelOf = useMemo(() => new Map(graph.floors.map((f) => [f.id, f.level])), [graph.floors]);

  const pad = 3;
  const minX = Math.min(0, ...nodes.map((n) => n.x)) - pad;
  const minY = Math.min(0, ...nodes.map((n) => n.y)) - pad;
  const maxX = Math.max(floor.width_m, ...nodes.map((n) => n.x)) + pad;
  const maxY = Math.max(floor.height_m, ...nodes.map((n) => n.y)) + pad;
  const w = maxX - minX;
  const h = maxY - minY;

  const edges = graph.edges.filter((e) => {
    const a = byId.get(e.a);
    const b = byId.get(e.b);
    return a && b && (a.floor_id === floor.id || b.floor_id === floor.id);
  });

  const exitInfo = new Map(exits.map((e) => [e.node_id, e]));
  const selected = devices.find((d) => d.id === selectedDevice);
  const routeNodes = (selected?.route ?? highlightNodes ?? []).map((id) => byId.get(id)).filter(Boolean) as GraphNode[];
  const floorDevices = devices.filter((d) => d.level === floor.level && d.x != null && d.y != null);

  const toMap = (e: MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  };

  return (
    <svg
      viewBox={`${minX} ${minY} ${w} ${h}`}
      className={cn("h-full w-full select-none rounded-lg bg-plan-bg", className)}
      role="img"
      aria-label={`Floor plan: ${floor.name}`}
      onClick={(e) => {
        if (!onBackgroundClick || e.target !== e.currentTarget) return;
        const p = toMap(e);
        if (p) onBackgroundClick(Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10, e);
      }}
    >
      {floor.plan_image ? (
        <image
          href={floor.plan_image.startsWith("http") ? floor.plan_image : `${API_PUBLIC_URL}${floor.plan_image}`}
          x={0}
          y={0}
          width={floor.width_m}
          height={floor.height_m}
          preserveAspectRatio="none"
          opacity={0.55}
          pointerEvents="none"
        />
      ) : (
        <rect x={0} y={0} width={floor.width_m} height={floor.height_m} fill="none" stroke="var(--plan-wall)" strokeWidth={0.25} strokeDasharray="0.6 0.4" pointerEvents="none" />
      )}

      {/* edges */}
      {edges.map((e, i) => {
        const a = byId.get(e.a)!;
        const b = byId.get(e.b)!;
        const vertical = a.floor_id !== b.floor_id;
        if (vertical) {
          const here = a.floor_id === floor.id ? a : b;
          const other = here === a ? b : a;
          const up = (levelOf.get(other.floor_id) ?? 0) > (levelOf.get(here.floor_id) ?? 0);
          return (
            <text key={`e${i}`} x={here.x + 1.1} y={here.y - 0.9} fontSize={0.9} fill="var(--muted-foreground)" pointerEvents="none">
              {e.kind === "lift" ? "⇅" : up ? "↑" : "↓"}
            </text>
          );
        }
        return (
          <line
            key={`e${i}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--plan-wall)"
            strokeWidth={e.kind === "door" ? 0.18 : 0.3}
            strokeDasharray={e.kind === "outdoor" ? "0.5 0.5" : undefined}
            pointerEvents="none"
          />
        );
      })}

      {/* selected route */}
      {routeNodes.length > 1 && (
        <polyline
          points={routeNodes.filter((n) => n.floor_id === floor.id).map((n) => `${n.x},${n.y}`).join(" ")}
          fill="none"
          stroke="var(--route)"
          strokeWidth={0.45}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray="1 0.5"
          pointerEvents="none"
        />
      )}

      {/* hazard + congestion halos */}
      {nodes.map((n) => {
        const hz = hazards[String(n.id)];
        const cong = Math.max(congestion[String(n.id)] ?? 0, 0);
        const pred = predicted[String(n.id)] ?? 0;
        return (
          <g key={`h${n.id}`} pointerEvents="none">
            {hz === "fire" && (
              <>
                <circle cx={n.x} cy={n.y} r={2.6} fill="var(--fire)" opacity={0.25} />
                <circle cx={n.x} cy={n.y} r={1.6} fill="var(--fire)" opacity={0.45} className="animate-pulse-ring" />
              </>
            )}
            {hz === "smoke" && <circle cx={n.x} cy={n.y} r={2.2} fill="var(--smoke)" opacity={0.28} />}
            {hz === "risk" && <circle cx={n.x} cy={n.y} r={1.9} fill="var(--risk)" opacity={0.22} />}
            {cong >= congestionThreshold * 0.5 && (
              <circle
                cx={n.x}
                cy={n.y}
                r={(NODE_R[n.type] ?? 0.7) + 0.5 + 0.35 * Math.min(cong, 2)}
                fill="none"
                stroke={cong >= congestionThreshold ? "var(--fire)" : "var(--risk)"}
                strokeWidth={0.22}
                opacity={0.8}
              />
            )}
            {pred >= congestionThreshold && cong < congestionThreshold && (
              <circle cx={n.x} cy={n.y} r={(NODE_R[n.type] ?? 0.7) + 0.7 + 0.35 * Math.min(pred, 2)} fill="none" stroke="var(--risk)" strokeWidth={0.15} strokeDasharray="0.4 0.3" />
            )}
          </g>
        );
      })}

      {/* nodes */}
      {nodes.map((n) => {
        const hz = hazards[String(n.id)];
        const r = NODE_R[n.type] ?? 0.7;
        const fill =
          hz === "fire" ? "var(--fire)" : n.type === "exit" ? "var(--safe)" : n.type === "refuge" ? "var(--info)" : n.type === "assembly" ? "var(--safe)" : "var(--card)";
        const isSel = selectedNode === n.id;
        const ex = exitInfo.get(n.id);
        return (
          <g
            key={n.id}
            onClick={(e) => {
              e.stopPropagation();
              onNodeClick?.(n, e);
            }}
            className={onNodeClick ? "cursor-pointer" : undefined}
          >
            {n.type === "stair" || n.type === "lift" ? (
              <rect x={n.x - r} y={n.y - r} width={r * 2} height={r * 2} rx={0.2} fill={fill} stroke={isSel ? "var(--primary)" : "var(--foreground)"} strokeWidth={isSel ? 0.3 : 0.12} />
            ) : (
              <circle cx={n.x} cy={n.y} r={r} fill={fill} stroke={isSel ? "var(--primary)" : "var(--foreground)"} strokeWidth={isSel ? 0.3 : 0.12} opacity={n.type === "corridor" ? 0.85 : 1} />
            )}
            {n.type === "exit" && (
              <text x={n.x} y={n.y + 0.35} fontSize={0.9} textAnchor="middle" fill="white" fontWeight={700} pointerEvents="none">
                EXIT
              </text>
            )}
            {showLabels && n.type !== "corridor" && (
              <text
                x={n.x}
                y={n.type === "stair" || n.type === "refuge" ? n.y - r - 0.5 : n.y + r + 1.0}
                fontSize={0.75}
                textAnchor="middle"
                fill="var(--foreground)"
                pointerEvents="none"
              >
                {n.name.length > 22 ? `${n.name.slice(0, 21)}…` : n.name}
              </text>
            )}
            {ex && (ex.assigned > 0 || ex.queue > 0) && (
              <text x={n.x} y={n.y - r - 0.4} fontSize={0.75} textAnchor="middle" fill="var(--foreground)" fontWeight={600} pointerEvents="none">
                {ex.queue > 0 ? `queue ${ex.queue} · ` : ""}
                {ex.assigned} assigned
              </text>
            )}
            {sosNodes.includes(n.id) && (
              <text x={n.x + r} y={n.y - r} fontSize={1.1} fill="var(--fire)" fontWeight={800} pointerEvents="none">
                SOS
              </text>
            )}
          </g>
        );
      })}

      {/* access points */}
      {showAccessPoints &&
        graph.access_points
          .filter((ap) => ap.floor_id === floor.id)
          .map((ap) => (
            <g key={ap.bssid} onClick={(e) => { e.stopPropagation(); onAccessPointClick?.(ap); }} className={onAccessPointClick ? "cursor-pointer" : undefined}>
              <path
                d={`M ${ap.x - 0.7} ${ap.y + 0.5} L ${ap.x} ${ap.y - 0.7} L ${ap.x + 0.7} ${ap.y + 0.5} Z`}
                fill={ap.calibrated ? "var(--info)" : "var(--muted-foreground)"}
                stroke="var(--background)"
                strokeWidth={0.1}
              />
              <title>{`${ap.ssid ?? "router"} ${ap.bssid}  P_ref ${ap.p_ref} dBm, η ${ap.eta}${ap.calibrated ? " (calibrated)" : ""}`}</title>
            </g>
          ))}

      {/* people */}
      {floorDevices.map((d) => {
        const isReal = d.kind === "real";
        // simulated people standing in the same room would overlap exactly: spread them a little
        const [jx, jy] = isReal ? [0, 0] : jitter(d.id);
        const cx = d.x! + jx;
        const cy = d.y! + jy;
        const color =
          d.status === "needs_help" ? "var(--fire)" : d.status === "safe" ? "var(--safe)" : d.status === "trapped" ? "var(--fire)" : isReal ? "var(--info)" : "var(--virtual)";
        const isSel = d.id === selectedDevice;
        return (
          <g key={d.id} onClick={(e) => { e.stopPropagation(); onDeviceClick?.(d); }} className={onDeviceClick ? "cursor-pointer" : undefined}>
            {isReal && d.spread_m ? <circle cx={cx} cy={cy} r={Math.min(d.spread_m, 8)} fill={color} opacity={0.12} pointerEvents="none" /> : null}
            <circle
              cx={cx}
              cy={cy}
              r={isReal ? 0.55 : 0.28}
              fill={color}
              stroke={isSel ? "var(--primary)" : isReal ? "white" : "none"}
              strokeWidth={isSel ? 0.25 : 0.12}
              opacity={isReal ? 1 : 0.75}
            />
            {isReal && !d.stairs_ok && (
              <text x={d.x! + 0.7} y={d.y! - 0.5} fontSize={0.8} pointerEvents="none">
                ♿
              </text>
            )}
            <title>{`${d.name}${d.flat ? ` (${d.flat})` : ""} · ${d.status} · ${d.source}${d.confidence != null ? ` · conf ${Math.round(d.confidence * 100)}%` : ""}`}</title>
          </g>
        );
      })}
      {overlay}
    </svg>
  );
}

function jitter(id: string): [number, number] {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  const a = ((h >>> 0) % 628) / 100;
  const r = 0.4 + (((h >>> 10) % 100) / 100) * 0.9;
  return [Math.cos(a) * r, Math.sin(a) * r];
}

export function MapLegend() {
  const items: [string, string][] = [
    ["var(--fire)", "Fire"],
    ["var(--smoke)", "Smoke"],
    ["var(--risk)", "At risk / congestion"],
    ["var(--safe)", "Exit"],
    ["var(--info)", "Resident phone / refuge"],
    ["var(--virtual)", "Simulated occupant"],
    ["var(--route)", "Selected route"],
  ];
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      {items.map(([c, l]) => (
        <span key={l} className="inline-flex items-center gap-1">
          <span className="inline-block size-2.5 rounded-full" style={{ background: c }} />
          {l}
        </span>
      ))}
    </div>
  );
}
