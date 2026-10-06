"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Field, Input, Select, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import { useBuilding, useGraph, useMe, useSignage } from "@/lib/hooks";

export default function SignagePage() {
  const id = Number(useParams<{ id: string }>().id);
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: building } = useBuilding(id);
  const { data: graph } = useGraph(id, building?.graph_version);
  const { data: signs } = useSignage(id);
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const isAdmin = me?.user.role === "society_admin";

  const create = useMutation({
    mutationFn: () => api.post(`/buildings/${id}/signage`, { name, node_id: Number(nodeId) }),
    onSuccess: () => {
      setName("");
      setNodeId("");
      qc.invalidateQueries({ queryKey: ["signage", id] });
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (sid: number) => api.del(`/signage/${sid}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["signage", id] }),
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">Digital signage</h1>
        <p className="text-sm text-muted-foreground">
          Open a display link full-screen on a TV or tablet in a corridor or lift lobby. It shows a live arrow to the safest exit from that spot and turns red during an incident.
        </p>
      </div>
      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle>Add a display</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Floor 2 lift lobby" />
            </Field>
            <Field label="Mounted at">
              <Select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
                <option value="">Choose a location…</option>
                {graph?.floors.map((f) => (
                  <optgroup key={f.id} label={f.name}>
                    {graph.nodes
                      .filter((n) => n.floor_id === f.id && n.type !== "assembly")
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.name}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </Select>
            </Field>
            <Button onClick={() => create.mutate()} disabled={!name || !nodeId || create.isPending}>
              <Plus /> Add
            </Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Displays</CardTitle>
          <CardDescription>{isAdmin ? "Each link contains a secret token - share it only with the device." : "Only society admins can see display links."}</CardDescription>
        </CardHeader>
        <CardContent>
          {signs && !signs.length && <EmptyState title="No displays yet" />}
          {signs && signs.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Location</TH>
                  <TH>Display link</TH>
                  {isAdmin && <TH />}
                </TR>
              </THead>
              <TBody>
                {signs.map((s) => (
                  <TR key={s.id}>
                    <TD className="font-medium">{s.name}</TD>
                    <TD className="text-xs">{s.node_name}</TD>
                    <TD>
                      {s.token ? (
                        <Link href={`/signage/${s.token}`} target="_blank" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                          Open display <ExternalLink className="size-3" />
                        </Link>
                      ) : (
                        "–"
                      )}
                    </TD>
                    {isAdmin && (
                      <TD>
                        <Button size="icon" variant="ghost" aria-label="Delete display" onClick={() => confirm(`Remove ${s.name}?`) && remove.mutate(s.id)}>
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
    </div>
  );
}
