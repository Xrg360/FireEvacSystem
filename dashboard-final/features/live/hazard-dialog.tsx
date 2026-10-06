"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlays";
import { api, errorMessage } from "@/lib/api/client";
import type { GraphNode, HazardLevel } from "@/lib/types";

export function HazardDialog({
  buildingId,
  node,
  current,
  occupancy,
  onClose,
}: {
  buildingId: number;
  node: GraphNode | null;
  current: string | undefined;
  occupancy: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const set = useMutation({
    mutationFn: (level: HazardLevel) => api.post(`/buildings/${buildingId}/hazards`, { node_id: node!.id, level }),
    onSuccess: (_d, level) => {
      toast.success(level === "none" ? `${node?.name} cleared` : `${node?.name} marked as ${level}`);
      qc.invalidateQueries({ queryKey: ["buildings"] });
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog open={node != null} onOpenChange={(o) => !o && onClose()}>
      {node && (
        <DialogContent title={node.name} description={`${node.type} · ${occupancy} people here now · capacity ${node.capacity}. Current hazard: ${current ?? "none"}.`}>
          <p className="text-sm text-muted-foreground">
            Rescuer confirmation overrides sensors and simulation. Marking fire opens an incident if none is active; routes avoid it within about a second.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="destructive" onClick={() => set.mutate("fire")} disabled={set.isPending}>
              Fire
            </Button>
            <Button className="bg-smoke text-white hover:bg-smoke/90" onClick={() => set.mutate("smoke")} disabled={set.isPending}>
              Smoke
            </Button>
            <Button className="bg-risk text-black hover:bg-risk/90" onClick={() => set.mutate("risk")} disabled={set.isPending}>
              At risk
            </Button>
            <Button variant="outline" onClick={() => set.mutate("none")} disabled={set.isPending}>
              Clear
            </Button>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
