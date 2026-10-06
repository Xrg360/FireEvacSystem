"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { FloorMap, MapLegend } from "@/components/floor-map";
import { Card, CardContent, CardHeader, CardTitle, EmptyState, Skeleton } from "@/components/ui/primitives";
import { DeviceTable } from "@/features/live/device-table";
import { FloorTabs } from "@/features/live/floor-tabs";
import { HazardDialog } from "@/features/live/hazard-dialog";
import { IncidentBar } from "@/features/live/incident-bar";
import { KpiRow } from "@/features/live/kpi-row";
import { ExitCapacity, SosPanel, UnaccountedPanel } from "@/features/live/side-panels";
import { useBuilding, useGraph, useLiveSnapshot } from "@/lib/hooks";
import { useBuildingSubscription } from "@/lib/realtime/socket-provider";
import type { GraphNode } from "@/lib/types";

export default function LiveCommandPage() {
  const id = Number(useParams<{ id: string }>().id);
  const { data: building } = useBuilding(id);
  useBuildingSubscription(id);
  const { snapshot, stale, ageMs } = useLiveSnapshot(id);
  const { data: graph } = useGraph(id, snapshot?.graph_version ?? building?.graph_version);
  const [chosenFloor, setChosenFloor] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hazardNode, setHazardNode] = useState<GraphNode | null>(null);

  const nodes = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);
  const nodeFloor = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n.floor_id])), [graph]);

  const selectedDevice = snapshot?.devices.find((d) => d.id === selected);
  // floor shown: follow the selected person, else the user's choice, else the floor on fire, else ground
  let floorId: number | null = null;
  if (graph) {
    const followed = selectedDevice?.level != null ? graph.floors.find((fl) => fl.level === selectedDevice.level) : undefined;
    const fireNode = snapshot && Object.entries(snapshot.hazards).find(([, l]) => l === "fire");
    const fireFloor = fireNode ? nodeFloor.get(Number(fireNode[0])) : undefined;
    floorId = followed?.id ?? chosenFloor ?? fireFloor ?? [...graph.floors].sort((x, y) => x.level - y.level)[0]?.id ?? null;
  }
  const setFloorId = (fid: number) => {
    setSelected(null);
    setChosenFloor(fid);
  };

  if (!building || !graph) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-[60vh] w-full" />
      </div>
    );
  }
  const floor = graph.floors.find((f) => f.id === floorId) ?? graph.floors[0];
  const threshold = building.settings.congestion_threshold;
  const sosNodes = (snapshot?.sos ?? []).map((s) => s.node_id).filter((n): n is number => n != null);

  return (
    <div className="flex flex-col gap-4">
      <IncidentBar building={building} stale={stale} ageMs={ageMs} />
      {snapshot ? <KpiRow kpis={snapshot.kpis} threshold={threshold} /> : <Skeleton className="h-20" />}

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <Card className="min-w-0">
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>Building layout & status</CardTitle>
            <FloorTabs floors={graph.floors} value={floor.id} onChange={setFloorId} snapshot={snapshot} nodeFloor={nodeFloor} />
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="aspect-[16/10] w-full">
              {graph.nodes.length ? (
                <FloorMap
                  graph={graph}
                  floor={floor}
                  hazards={snapshot?.hazards}
                  congestion={snapshot?.congestion}
                  predicted={snapshot?.predicted_congestion}
                  devices={snapshot?.devices}
                  exits={snapshot?.exits}
                  selectedDevice={selected}
                  congestionThreshold={threshold}
                  sosNodes={sosNodes}
                  onDeviceClick={(d) => setSelected(d.id === selected ? null : d.id)}
                  onNodeClick={(n) => setHazardNode(n)}
                  className={stale ? "opacity-70 grayscale-[40%]" : undefined}
                />
              ) : (
                <EmptyState title="No floor plan yet" description="An admin can draw this building in the floor plan editor." />
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <MapLegend />
              <p className="text-[11px] text-muted-foreground">Click a room to mark fire/smoke · click a person to see their route</p>
            </div>
            {selectedDevice && (
              <div className="rounded-lg border bg-muted/40 p-2 text-xs">
                <span className="font-semibold">{selectedDevice.name}</span>
                {selectedDevice.route.length > 1 ? (
                  <span className="text-muted-foreground">
                    {" "}
                    → {selectedDevice.route.map((n) => nodes.get(n)?.name ?? n).join(" → ")} ({selectedDevice.remaining_m} m)
                  </span>
                ) : (
                  <span className="text-muted-foreground"> - no active route ({selectedDevice.status})</span>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-4">
          <SosPanel buildingId={id} sos={snapshot?.sos ?? []} nodes={nodes} />
          <ExitCapacity exits={snapshot?.exits ?? []} />
          {building.incident && <UnaccountedPanel people={snapshot?.unaccounted ?? []} nodes={nodes} />}
        </div>
      </div>

      <DeviceTable devices={snapshot?.devices ?? []} nodes={nodes} selected={selected} onSelect={setSelected} />

      <HazardDialog
        buildingId={id}
        node={hazardNode}
        current={hazardNode ? snapshot?.hazards[String(hazardNode.id)] : undefined}
        occupancy={hazardNode ? snapshot?.occupancy[String(hazardNode.id)] ?? 0 : 0}
        onClose={() => setHazardNode(null)}
      />
    </div>
  );
}
