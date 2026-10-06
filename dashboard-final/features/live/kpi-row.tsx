import { AlertTriangle, Flame, Footprints, Gauge, HeartPulse, ShieldCheck, Smartphone, UserX } from "lucide-react";

import { Card } from "@/components/ui/primitives";
import type { Kpis } from "@/lib/types";
import { cn, pct } from "@/lib/utils";

function Kpi({ icon: Icon, label, value, sub, tone }: { icon: typeof Flame; label: string; value: string | number; sub?: string; tone?: "fire" | "safe" | "risk" }) {
  return (
    <Card className={cn("flex items-start gap-3 p-3", tone === "fire" && "border-fire/50 bg-fire/5")}>
      <Icon className={cn("mt-0.5 size-4 text-muted-foreground", tone === "fire" && "text-fire", tone === "safe" && "text-safe", tone === "risk" && "text-smoke")} />
      <div className="min-w-0">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <p className="text-xl font-semibold leading-tight tabular-nums">{value}</p>
        {sub && <p className="truncate text-[11px] text-muted-foreground">{sub}</p>}
      </div>
    </Card>
  );
}

export function KpiRow({ kpis, threshold }: { kpis: Kpis; threshold: number }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
      <Kpi icon={Smartphone} label="Active devices" value={kpis.active_devices} sub={`${kpis.real_devices} phones · ${kpis.virtual_occupants} simulated`} />
      <Kpi icon={Footprints} label="Avg path length" value={`${kpis.avg_path_length_m} m`} sub={`${kpis.avg_path_nodes} nodes`} />
      <Kpi icon={Gauge} label="Congestion rate" value={pct(kpis.congestion_rate)} sub={`spaces ≥ ${Math.round(threshold * 100)}% full`} tone={kpis.congestion_rate > 0.15 ? "risk" : undefined} />
      <Kpi icon={Flame} label="Fire alerts" value={kpis.fire_alerts} tone={kpis.fire_alerts ? "fire" : undefined} />
      <Kpi icon={ShieldCheck} label="Evacuated" value={kpis.evacuated} tone="safe" />
      <Kpi icon={UserX} label="Unaccounted" value={kpis.unaccounted} sub="residents not yet safe" tone={kpis.unaccounted ? "risk" : undefined} />
      <Kpi icon={HeartPulse} label="Need help" value={kpis.needs_help} tone={kpis.needs_help ? "fire" : undefined} />
      <Kpi icon={AlertTriangle} label="Trapped / in refuge" value={`${kpis.trapped} / ${kpis.in_refuge}`} tone={kpis.trapped ? "fire" : undefined} />
    </div>
  );
}
