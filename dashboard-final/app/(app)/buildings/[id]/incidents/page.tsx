"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { useIncidents } from "@/lib/hooks";
import { formatDuration } from "@/lib/utils";

export default function IncidentsPage() {
  const id = Number(useParams<{ id: string }>().id);
  const { data, isLoading } = useIncidents(id);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Incidents, drills & simulations</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <Skeleton className="h-40" />}
        {data && !data.length && <EmptyState title="No incidents recorded" description="Drills, simulated fires and real incidents appear here with their post-incident metrics and replay." />}
        {data && data.length > 0 && (
          <Table>
            <THead>
              <TR>
                <TH>#</TH>
                <TH>Type</TH>
                <TH>Started</TH>
                <TH>Duration</TH>
                <TH>Status</TH>
                <TH>Avg evacuation</TH>
                <TH>Route updates</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {data.map((i) => (
                <TR key={i.id}>
                  <TD className="tabular-nums">{i.id}</TD>
                  <TD>
                    <Badge variant={i.kind === "fire" ? "fire" : "info"}>{i.kind}</Badge> {i.is_simulation && <Badge variant="muted">simulated</Badge>}
                  </TD>
                  <TD className="text-xs">{i.started_at ? new Date(i.started_at).toLocaleString() : "–"}</TD>
                  <TD className="text-xs tabular-nums">{formatDuration(i.metrics?.duration_s)}</TD>
                  <TD>
                    <Badge variant={i.status === "evacuating" || i.status === "detected" ? "fire" : "safe"}>{i.status.replace("_", " ")}</Badge>
                  </TD>
                  <TD className="text-xs tabular-nums">{formatDuration(i.metrics?.avg_evac_time_s ?? (i.metrics?.simulation?.avg_evac_time_s as number | undefined))}</TD>
                  <TD className="text-xs tabular-nums">{i.metrics?.route_assignments ?? "–"}</TD>
                  <TD>
                    <Link href={`/incidents/${i.id}`} className="text-sm font-medium text-primary hover:underline">
                      Replay →
                    </Link>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
