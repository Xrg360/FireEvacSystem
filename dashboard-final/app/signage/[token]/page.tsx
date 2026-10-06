"use client";

// Full-screen kiosk display (paper §III-E dynamic digital signage). No login: the secret token
// in the URL identifies the display. Shows a big arrow to the safest exit from where it hangs.
import { ArrowDown, ArrowUp, Flame, ShieldAlert } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { io } from "socket.io-client";

import { API_PUBLIC_URL } from "@/lib/realtime/socket-provider";
import { SignageSchema } from "@/lib/schemas";
import type { SignageState } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function SignageDisplay() {
  const token = useParams<{ token: string }>().token;
  const [state, setState] = useState<SignageState | null>(null);
  const [meta, setMeta] = useState<{ name: string; building: string } | null>(null);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_PUBLIC_URL}/api/signage/display/${token}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("Unknown display");
        const d = await r.json();
        setMeta({ name: d.signage.name, building: d.building.name });
        setState(d.state);
      })
      .catch((e) => setError(e.message));
    const s = io(API_PUBLIC_URL, { auth: { signage_token: token }, transports: ["websocket", "polling"] });
    s.on("connect", () => setOnline(true));
    s.on("disconnect", () => setOnline(false));
    s.on("signage.update", (raw: unknown) => {
      const p = SignageSchema.safeParse(raw);
      if (p.success) setState(p.data as SignageState);
    });
    return () => {
      s.disconnect();
    };
  }, [token]);

  if (error) return <div className="flex min-h-dvh items-center justify-center bg-black text-2xl text-white">{error}</div>;
  const evac = state?.incident;
  const danger = state?.status === "danger";

  return (
    <main
      className={cn(
        "flex min-h-dvh flex-col items-center justify-between p-6 text-white transition-colors",
        danger ? "bg-red-950" : evac ? "bg-red-700" : "bg-emerald-800",
      )}
    >
      <header className="flex w-full items-center justify-between text-lg opacity-90">
        <span>
          {meta?.building} · {meta?.name}
        </span>
        <span className={cn("rounded px-2 py-0.5 text-sm", online ? "bg-black/30" : "bg-yellow-400 text-black")}>{online ? "LIVE" : "OFFLINE - follow green exit signs"}</span>
      </header>

      <section className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
        {evac && (
          <p className="flex items-center gap-3 text-4xl font-black tracking-wide sm:text-6xl">
            <Flame className="size-12 animate-pulse" /> EVACUATE
          </p>
        )}
        {danger ? (
          <ShieldAlert className="size-48" />
        ) : state?.arrow_deg != null ? (
          <div className="relative flex items-center justify-center">
            <svg viewBox="0 0 100 100" className="size-[min(60vw,50vh)] drop-shadow-xl" style={{ transform: `rotate(${state.arrow_deg}deg)` }} aria-label={`Arrow pointing ${state.arrow_deg} degrees`}>
              <path d="M50 6 L86 50 H63 V94 H37 V50 H14 Z" fill="white" />
            </svg>
            {state.vertical && (
              <span className="absolute -right-16 flex flex-col items-center text-3xl font-bold">
                {state.vertical === "down" ? <ArrowDown className="size-14" /> : <ArrowUp className="size-14" />}
                {state.vertical === "down" ? "DOWN" : "UP"}
              </span>
            )}
          </div>
        ) : null}
        <p className="max-w-4xl text-3xl font-semibold sm:text-5xl">{state?.message ?? "Connecting…"}</p>
        {state?.exit && state.distance_m != null && <p className="text-xl opacity-90 sm:text-2xl">{state.distance_m} m to {state.exit}</p>}
      </section>

      <footer className="flex w-full flex-wrap justify-center gap-3 text-base">
        {state?.exits?.map((e) => (
          <span key={e.name} className={cn("rounded-lg px-3 py-1", e.hazard === "fire" ? "bg-black/60 line-through" : e.hazard === "smoke" ? "bg-orange-500/80" : "bg-black/25")}>
            {e.name}
            {e.hazard !== "none" ? ` - ${e.hazard.toUpperCase()}` : ""}
          </span>
        ))}
      </footer>
    </main>
  );
}
