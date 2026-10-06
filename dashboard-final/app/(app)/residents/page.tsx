"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Accessibility, Check, Plus, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger, Tabs, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Badge, Card, CardContent, EmptyState, Field, Input, Select, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import { useBuildings, useMe, useResidents } from "@/lib/hooks";
import type { Resident } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

function StaffDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", email: "", password: "", phone: "", role: "rescuer" });
  const create = useMutation({
    mutationFn: () => api.post("/staff", f),
    onSuccess: () => {
      toast.success("Account created");
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["residents"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Plus /> Add rescuer / staff
        </Button>
      </DialogTrigger>
      <DialogContent title="Create a staff account" description="Rescuers see the live command view; surveyors can record Wi-Fi surveys in the app.">
        <div className="flex flex-col gap-3">
          <Field label="Name">
            <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </Field>
          <Field label="Email">
            <Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          </Field>
          <Field label="Temporary password (min 8)">
            <Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          </Field>
          <Field label="Phone">
            <Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          </Field>
          <Field label="Role">
            <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="rescuer">Rescuer</option>
              <option value="surveyor">Surveyor</option>
              <option value="society_admin">Society admin</option>
            </Select>
          </Field>
          <Button onClick={() => create.mutate()} disabled={!f.name || !f.email || f.password.length < 8 || create.isPending}>
            Create
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function ResidentsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("pending");
  const { data: me } = useMe();
  const { data: buildings } = useBuildings();
  const { data: people, isLoading } = useResidents(tab === "all" ? undefined : tab);
  const bname = new Map((buildings ?? []).map((b) => [b.id, b.name]));

  const act = useMutation({
    mutationFn: ({ u, action }: { u: Resident; action: "approve" | "reject" }) => api.post(`/residents/${u.id}/${action}`),
    onSuccess: (_d, { u, action }) => {
      toast.success(`${u.name} ${action === "approve" ? "approved" : "rejected"}`);
      qc.invalidateQueries({ queryKey: ["residents"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const patch = useMutation({
    mutationFn: ({ u, body }: { u: Resident; body: Record<string, unknown> }) => api.patch(`/residents/${u.id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["residents"] }),
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (me && me.user.role !== "society_admin") return <EmptyState title="Society admins only" />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Residents</h1>
          <p className="text-sm text-muted-foreground">
            Residents sign up in the app with join code <span className="font-mono font-semibold text-foreground">{me?.society?.join_code}</span> and wait here for approval.
          </p>
        </div>
        <StaffDialog />
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="pending">Pending approval</TabsTrigger>
          <TabsTrigger value="approved">Approved</TabsTrigger>
          <TabsTrigger value="rejected">Rejected</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card>
        <CardContent className="pt-4">
          {isLoading && <Skeleton className="h-40" />}
          {people && !people.length && <EmptyState title={tab === "pending" ? "No one is waiting for approval" : "No accounts"} />}
          {people && people.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Building / flat</TH>
                  <TH>Contact</TH>
                  <TH>Mobility</TH>
                  <TH>Role</TH>
                  <TH>App / push</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {people.map((u) => (
                  <TR key={u.id}>
                    <TD>
                      <p className="font-medium">{u.name}</p>
                      <p className="text-[11px] text-muted-foreground">signed up {timeAgo(u.created_at)}</p>
                    </TD>
                    <TD className="text-xs">
                      {u.building_id ? bname.get(u.building_id) : "–"} · {u.flat ?? "–"}
                    </TD>
                    <TD className="text-xs">
                      {u.email}
                      <br />
                      {u.phone}
                    </TD>
                    <TD>
                      <label className="flex items-center gap-1.5 text-xs">
                        <input type="checkbox" checked={!u.stairs_ok} onChange={(e) => patch.mutate({ u, body: { stairs_ok: !e.target.checked } })} />
                        <Accessibility className="size-3.5" /> can&apos;t use stairs
                      </label>
                      {u.mobility_notes && <p className="text-[11px] text-muted-foreground">{u.mobility_notes}</p>}
                    </TD>
                    <TD>
                      <Badge variant="outline">{u.role.replace("_", " ")}</Badge>
                    </TD>
                    <TD className="text-xs">
                      {u.devices.length ? u.devices.map((d) => <div key={d.id}>{d.model ?? "phone"} · {d.push ? "push ✓" : "no push"}</div>) : "not installed"}
                    </TD>
                    <TD className="whitespace-nowrap">
                      {u.status !== "approved" && (
                        <Button size="sm" variant="safe" onClick={() => act.mutate({ u, action: "approve" })}>
                          <Check /> Approve
                        </Button>
                      )}
                      {u.status !== "rejected" && u.id !== me?.user.id && (
                        <Button size="sm" variant="ghost" onClick={() => act.mutate({ u, action: "reject" })}>
                          <X /> Reject
                        </Button>
                      )}
                    </TD>
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
