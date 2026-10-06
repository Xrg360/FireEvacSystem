"use client";

import { Accessibility } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, Card, CardContent, CardHeader, CardTitle, Progress, Select, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import type { GraphNode, LiveDevice } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  wifi_pf: "Wi-Fi",
  manual: "Self-reported",
  gps: "GPS (outside)",
  last_known: "Last known",
  unknown: "Unknown",
  simulated: "Simulated",
};

export function DeviceTable({
  devices,
  nodes,
  selected,
  onSelect,
}: {
  devices: LiveDevice[];
  nodes: Map<number, GraphNode>;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [filter, setFilter] = useState<"real" | "all" | "routed">("real");
  const rows = useMemo(() => {
    const list = devices.filter((d) => (filter === "real" ? d.kind === "real" : filter === "routed" ? d.route.length > 1 : true));
    return list.sort((a, b) => Number(b.status === "needs_help") - Number(a.status === "needs_help") || (a.kind === "real" ? -1 : 1));
  }, [devices, filter]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Active device details</CardTitle>
        <Select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="h-8 w-40 text-xs" aria-label="Filter devices">
          <option value="real">Resident phones</option>
          <option value="routed">Everyone with a route</option>
          <option value="all">All (incl. simulated)</option>
        </Select>
      </CardHeader>
      <CardContent className="max-h-[28rem] overflow-y-auto">
        <Table>
          <THead>
            <TR>
              <TH>Person / device</TH>
              <TH>Current location</TH>
              <TH>Assigned exit</TH>
              <TH className="min-w-48">Path progress</TH>
              <TH>Position source</TH>
              <TH>Status</TH>
            </TR>
          </THead>
          <TBody>
            {rows.slice(0, 300).map((d) => (
              <TR
                key={d.id}
                className={cn("cursor-pointer", selected === d.id && "bg-accent")}
                onClick={() => onSelect(selected === d.id ? null : d.id)}
                aria-selected={selected === d.id}
              >
                <TD>
                  <p className="font-medium">
                    {d.name} {!d.stairs_ok && <Accessibility className="inline size-3 text-fire" aria-label="cannot use stairs" />}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{d.flat ?? (d.kind === "virtual" ? "simulated" : d.id.slice(0, 8))}</p>
                </TD>
                <TD className="text-xs">
                  {d.node_id != null ? nodes.get(d.node_id)?.name ?? d.node_id : "-"}
                  {d.x != null && <p className="font-mono text-[10px] text-muted-foreground">({d.x.toFixed(1)}, {d.y?.toFixed(1)}) L{d.level}</p>}
                </TD>
                <TD className="text-xs">
                  {d.goal != null ? nodes.get(d.goal)?.name ?? d.goal : "-"}
                  {d.goal_type === "refuge" && <Badge variant="info" className="ml-1">refuge</Badge>}
                </TD>
                <TD>
                  {d.route.length > 1 ? (
                    <div className="flex flex-col gap-1">
                      <Progress value={(d.progress ?? 0) * 100} />
                      <p className="truncate text-[11px] text-muted-foreground" title={d.route.map((n) => nodes.get(n)?.name ?? n).join(" → ")}>
                        {d.remaining_m} m left · {d.route.map((n) => nodes.get(n)?.name ?? n).join(" → ")}
                      </p>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">-</span>
                  )}
                </TD>
                <TD className="text-xs">
                  {SOURCE_LABEL[d.source] ?? d.source}
                  {d.kind === "real" && <p className="text-[11px] text-muted-foreground">conf {Math.round(d.confidence * 100)}%{d.needs_picker ? " · asked to confirm" : ""}</p>}
                </TD>
                <TD>
                  <Badge variant={d.status === "safe" ? "safe" : d.status === "needs_help" || d.status === "trapped" ? "fire" : d.status === "refuge" ? "info" : "muted"}>
                    {d.status.replace("_", " ")}
                  </Badge>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {!rows.length && <p className="py-6 text-center text-xs text-muted-foreground">No devices reporting. Positions are only shared during an incident, drill or simulation.</p>}
      </CardContent>
    </Card>
  );
}
