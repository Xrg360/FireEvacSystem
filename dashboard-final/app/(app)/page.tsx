"use client";

import { Building2, Flame, PlayCircle } from "lucide-react";
import Link from "next/link";

import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Skeleton } from "@/components/ui/primitives";
import { useBuildings, useMe } from "@/lib/hooks";
import { timeAgo } from "@/lib/utils";

export default function OverviewPage() {
  const { data: buildings, isLoading } = useBuildings();
  const { data: me } = useMe();

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">{me?.society?.name ?? "Buildings"}</h1>
        <p className="text-sm text-muted-foreground">
          Choose a building to open its live command view.
          {me?.society?.join_code && (
            <>
              {" "}
              Resident join code: <span className="font-mono font-semibold text-foreground">{me.society.join_code}</span>
            </>
          )}
        </p>
      </div>
      {isLoading && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      )}
      {buildings && !buildings.length && <EmptyState title="No buildings yet" description="A society admin can create one and draw it in the floor plan editor." />}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {buildings?.map((b) => (
          <Link key={b.id} href={`/buildings/${b.id}`} className="group">
            <Card className={b.incident ? "border-fire bg-fire/5" : "transition-colors group-hover:border-primary/50"}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <Building2 className="size-4 text-muted-foreground" />
                    {b.name}
                  </span>
                  {b.mode === "simulation" && (
                    <Badge variant="info">
                      <PlayCircle className="size-3" /> Simulation
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription>Graph v{b.graph_version}</CardDescription>
              </CardHeader>
              <CardContent>
                {b.incident ? (
                  <p className="flex items-center gap-1.5 text-sm font-semibold text-fire">
                    <Flame className="size-4" />
                    {b.incident.kind === "drill" ? "Drill in progress" : "FIRE - evacuation in progress"} · started {timeAgo(b.incident.started_at)}
                  </p>
                ) : (
                  <p className="text-sm text-safe">No active incident</p>
                )}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
