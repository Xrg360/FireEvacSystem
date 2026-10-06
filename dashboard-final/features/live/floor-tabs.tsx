"use client";

import type { Floor, Snapshot } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Floor switcher with per-floor alert counts (fire / people). */
export function FloorTabs({
  floors,
  value,
  onChange,
  snapshot,
  nodeFloor,
}: {
  floors: Floor[];
  value: number;
  onChange: (floorId: number) => void;
  snapshot?: Snapshot;
  nodeFloor: Map<number, number>;
}) {
  const sorted = [...floors].sort((a, b) => b.level - a.level);
  return (
    <div className="flex flex-wrap gap-1" role="tablist" aria-label="Floors">
      {sorted.map((f) => {
        const fires = snapshot ? Object.entries(snapshot.hazards).filter(([n, l]) => l === "fire" && nodeFloor.get(Number(n)) === f.id).length : 0;
        const people = snapshot ? snapshot.devices.filter((d) => d.level === f.level && !["safe", "trapped"].includes(d.status)).length : 0;
        return (
          <button
            key={f.id}
            role="tab"
            aria-selected={value === f.id}
            onClick={() => onChange(f.id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors",
              value === f.id ? "border-primary bg-primary/10 font-medium" : "hover:bg-accent",
              fires > 0 && "border-fire text-fire",
            )}
          >
            {f.name}
            {people > 0 && <span className="rounded bg-muted px-1 tabular-nums text-muted-foreground">{people}</span>}
            {fires > 0 && <span className="rounded bg-fire px-1 text-white">🔥{fires}</span>}
          </button>
        );
      })}
    </div>
  );
}
