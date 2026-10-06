"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api/client";
import { useBuilding } from "@/lib/hooks";
import type { Building, BuildingSettings } from "@/lib/types";

const GROUPS: { title: string; description: string; fields: [keyof BuildingSettings, string, string][] }[] = [
  {
    title: "Routing (A* edge cost)",
    description: "cost = length × (1 + α·hazard + β·congestion) + γ·exit wait. Higher values avoid that factor more strongly.",
    fields: [
      ["alpha", "α - hazard weight", "smoke counts as 1, risk 0.25; fire is always impassable"],
      ["beta", "β - congestion weight", "multiplies occupancy ÷ capacity"],
      ["gamma", "γ - exit load weight", "spreads people across exits by flow rate"],
      ["congestion_threshold", "Congestion threshold", "occupancy ÷ capacity that counts as congested (triggers rerouting)"],
      ["reroute_improvement", "Reroute only if cheaper by", "fraction, e.g. 0.15 = 15% - prevents flip-flopping"],
      ["reroute_cooldown_s", "Reroute cooldown (s)", "minimum time between congestion reroutes per person"],
    ],
  },
  {
    title: "Positioning",
    description: "Wi-Fi particle filter (paper Alg. 1) with eq. 4/5 bounds and fingerprinting.",
    fields: [
      ["rssi_uncertainty_db", "RSSI uncertainty (dB)", "the 'uncertainty' in eq. 4/5"],
      ["floor_attenuation_db", "Floor slab attenuation (dB)", "signal lost per floor between phone and router"],
      ["particles", "Particles per phone", "more is smoother but slower"],
      ["low_confidence", "Ask 'Where are you?' below", "position confidence (0–1)"],
      ["floor_confirm_confidence", "Ask to confirm floor below", "floor confidence (0–1)"],
    ],
  },
  {
    title: "Fire detection",
    description: "Any one rule marks the sensor's room on fire.",
    fields: [
      ["smoke_threshold", "Smoke threshold", "sensor units (e.g. MQ-2 ppm equivalent)"],
      ["temp_threshold_c", "Temperature threshold (°C)", "fixed-temperature heat detectors are usually 57 °C"],
      ["rate_of_rise_c_per_min", "Rate of rise (°C/min)", "rate-of-rise heat detector rule"],
    ],
  },
];

export default function SettingsPage() {
  const id = Number(useParams<{ id: string }>().id);
  const { data: building } = useBuilding(id);
  if (!building) return <Skeleton className="h-96" />;
  return <SettingsForm key={building.id} building={building} />;
}

function SettingsForm({ building }: { building: Building }) {
  const id = building.id;
  const qc = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(building.settings).map(([k, v]) => [k, String(v)])),
  );
  const [name, setName] = useState(building.name);

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/buildings/${id}`, {
        name,
        settings: Object.fromEntries(Object.entries(form).map(([k, v]) => [k, Number(v)])),
      }),
    onSuccess: () => {
      toast.success("Settings saved - the engine applies them on its next tick");
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const invalid = Object.values(form).some((v) => v === "" || !Number.isFinite(Number(v)));

  return (
    <form
      className="flex max-w-4xl flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Settings - {building.name}</h1>
        <Button type="submit" disabled={invalid || save.isPending}>
          Save
        </Button>
      </div>
      <Card>
        <CardContent className="pt-4">
          <Field label="Building name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </CardContent>
      </Card>
      {GROUPS.map((g) => (
        <Card key={g.title}>
          <CardHeader>
            <CardTitle>{g.title}</CardTitle>
            <CardDescription>{g.description}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {g.fields.map(([key, label, hint]) => (
              <Field key={key} label={label} hint={hint}>
                <Input type="number" step="any" value={form[key] ?? ""} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </Field>
            ))}
          </CardContent>
        </Card>
      ))}
    </form>
  );
}
