"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Accessibility, CheckCircle2, DoorOpen, Phone } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Progress } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import type { ExitInfo, GraphNode, SosRequest, UnaccountedResident } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

export function ExitCapacity({ exits }: { exits: ExitInfo[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <DoorOpen className="size-4" /> Exit capacity
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {exits.map((e) => {
          // minutes needed to clear everyone assigned, at the exit's rated flow
          const clearMin = e.assigned / Math.max(e.flow_per_min, 1);
          const load = Math.min(100, (clearMin / 2) * 100); // 2 minutes of queue = full bar
          return (
            <div key={e.node_id} className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate font-medium">{e.name}</span>
                <span className="tabular-nums text-muted-foreground">
                  {e.hazard !== "none" && (
                    <Badge variant={e.hazard === "fire" ? "fire" : e.hazard === "smoke" ? "smoke" : "risk"} className="mr-1 px-1 py-0 text-[10px]">
                      {e.hazard}
                    </Badge>
                  )}
                  {e.assigned} assigned · {e.queue} at exit · {e.flow_per_min}/min
                </span>
              </div>
              <Progress value={e.hazard === "fire" ? 100 : load} tone={e.hazard === "fire" ? "fire" : load > 75 ? "smoke" : load > 40 ? "risk" : "safe"} />
            </div>
          );
        })}
        {!exits.length && <p className="text-xs text-muted-foreground">No exits defined.</p>}
      </CardContent>
    </Card>
  );
}

export function SosPanel({ buildingId, sos, nodes }: { buildingId: number; sos: SosRequest[]; nodes: Map<number, GraphNode> }) {
  const qc = useQueryClient();
  const resolve = useMutation({
    mutationFn: (id: number) => api.post(`/sos/${id}/resolve`),
    onSuccess: () => {
      toast.success("Marked as resolved");
      qc.invalidateQueries({ queryKey: ["sos", buildingId] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card className={sos.length ? "border-fire/60" : undefined}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>SOS requests</span>
          {sos.length > 0 && <Badge variant="fire">{sos.length} open</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {sos.map((s) => (
          <div key={s.id} className="rounded-lg border border-fire/40 bg-fire/5 p-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">
                {s.user_name ?? "Resident"} {s.flat && <span className="font-normal text-muted-foreground">· {s.flat}</span>}
              </span>
              <Badge variant="fire" className="uppercase">{s.kind}</Badge>
            </div>
            <p className="mt-1 text-muted-foreground">
              {s.node_id != null ? `Last seen: ${nodes.get(s.node_id)?.name ?? `node ${s.node_id}`}` : "Location unknown"} · {timeAgo(s.created_at)}
              {!s.stairs_ok && (
                <span className="ml-1 inline-flex items-center gap-0.5 text-fire">
                  <Accessibility className="size-3" /> cannot use stairs
                </span>
              )}
            </p>
            {s.note && <p className="mt-1">“{s.note}”</p>}
            <div className="mt-2 flex gap-2">
              {s.phone && (
                <Button asChild size="sm" variant="outline">
                  <a href={`tel:${s.phone}`}>
                    <Phone /> Call
                  </a>
                </Button>
              )}
              <Button size="sm" variant="secondary" onClick={() => resolve.mutate(s.id)} disabled={resolve.isPending}>
                <CheckCircle2 /> Resolved
              </Button>
            </div>
          </div>
        ))}
        {!sos.length && <p className="text-xs text-muted-foreground">No open requests.</p>}
      </CardContent>
    </Card>
  );
}

const STATUS_BADGE: Record<string, "risk" | "info" | "fire" | "muted"> = { unknown: "muted", evacuating: "info", needs_help: "fire" };

export function UnaccountedPanel({ people, nodes }: { people: UnaccountedResident[]; nodes: Map<number, GraphNode> }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Not yet safe</span>
          <span className="text-xs font-normal text-muted-foreground">{people.length}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
        {people.map((p) => (
          <div key={p.device_id} className="flex items-center justify-between gap-2 rounded-md px-1 py-1 text-xs hover:bg-muted/50">
            <div className="min-w-0">
              <p className="truncate font-medium">
                {p.name} {!p.stairs_ok && <Accessibility className="inline size-3 text-fire" aria-label="cannot use stairs" />}
              </p>
              <p className="truncate text-muted-foreground">
                {p.flat ?? "-"} · {p.last_fix?.node_id != null ? nodes.get(p.last_fix.node_id)?.name ?? "?" : "no position yet"}
                {p.last_fix?.source === "manual" ? " (self-reported)" : ""}
              </p>
            </div>
            <Badge variant={STATUS_BADGE[p.status] ?? "muted"}>{p.status.replace("_", " ")}</Badge>
          </div>
        ))}
        {!people.length && <p className="text-xs text-muted-foreground">Everyone registered is accounted for.</p>}
      </CardContent>
    </Card>
  );
}
