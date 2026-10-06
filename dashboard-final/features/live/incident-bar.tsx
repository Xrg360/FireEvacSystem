"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellRing, CheckCircle2, Flame, WifiOff } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/overlays";
import { Badge } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import type { Building, Incident } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { formatDuration } from "@/lib/utils";

export function IncidentBar({ building, stale, ageMs }: { building: Building; stale: boolean; ageMs: number | null }) {
  const qc = useQueryClient();
  const incident = building.incident;
  const [open, setOpen] = useState(false);

  const start = useMutation({
    mutationFn: (kind: "fire" | "drill") => api.post<Incident>(`/buildings/${building.id}/incidents`, { kind }),
    onSuccess: (inc) => {
      toast.error(`${inc.kind === "drill" ? "Drill" : "Fire incident"} started - residents alerted`);
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const status = useMutation({
    mutationFn: (s: "all_clear" | "closed") => api.post(`/incidents/${incident!.id}/status`, { status: s }),
    onSuccess: () => {
      toast.success("All clear sent to residents");
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const now = useNow();
  const elapsed = incident?.started_at ? (now - Date.parse(incident.started_at)) / 1000 : null;

  return (
    <div className="flex flex-col gap-2">
      {stale && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-smoke bg-smoke/10 px-3 py-2 text-sm font-medium text-smoke">
          <WifiOff className="size-4" />
          STALE DATA - no live update for {ageMs != null ? formatDuration(ageMs / 1000) : "a while"}. The map shows the last known state; do not treat empty areas as clear.
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <h1 className="truncate text-lg font-semibold">{building.name}</h1>
          <Badge variant={building.mode === "simulation" ? "info" : "outline"}>{building.mode === "simulation" ? "Simulation mode" : "Live"}</Badge>
          {incident && (
            <Badge variant="fire" className="text-sm">
              <Flame className="size-3.5" />
              {incident.kind === "drill" ? "DRILL" : "FIRE"} · {incident.status} {elapsed != null && `· ${formatDuration(elapsed)}`}
              {incident.is_simulation && " · simulated"}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {incident ? (
            <Button variant="safe" onClick={() => status.mutate("all_clear")} disabled={status.isPending}>
              <CheckCircle2 /> Declare all clear
            </Button>
          ) : (
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button variant="destructive">
                  <BellRing /> Alert residents
                </Button>
              </DialogTrigger>
              <DialogContent title="Alert every resident of this building?" description="Phones get a full-screen alarm and start sharing their location for routing.">
                <div className="grid gap-2 sm:grid-cols-2">
                  <Button variant="outline" size="lg" onClick={() => start.mutate("drill")} disabled={start.isPending}>
                    Start a drill
                  </Button>
                  <Button variant="destructive" size="lg" onClick={() => start.mutate("fire")} disabled={start.isPending}>
                    <Flame /> Declare a FIRE
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>
    </div>
  );
}
