"use client";

import {
  Activity,
  Building2,
  Cpu,
  Flame,
  History,
  LogOut,
  MonitorSmartphone,
  Moon,
  PenTool,
  PlayCircle,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSyncExternalStore, type ReactNode } from "react";

import { Badge } from "@/components/ui/primitives";
import { useBuildings, useMe } from "@/lib/hooks";
import { useLive } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

const BUILDING_NAV = [
  { href: "", label: "Live command", icon: Activity },
  { href: "/simulation", label: "Simulation", icon: PlayCircle },
  { href: "/incidents", label: "Incidents & replay", icon: History },
  { href: "/sensors", label: "Sensors", icon: Cpu },
  { href: "/signage", label: "Signage", icon: MonitorSmartphone },
  { href: "/editor", label: "Floor plan editor", icon: PenTool, admin: true },
  { href: "/settings", label: "Settings", icon: Settings, admin: true },
];

function ConnectionPill() {
  const status = useLive((s) => s.status);
  const tone = status === "connected" ? "bg-safe" : status === "connecting" ? "bg-risk" : "bg-fire";
  const label = status === "connected" ? "Live" : status === "connecting" ? "Connecting…" : "Disconnected";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status" aria-live="polite">
      <span className={cn("size-2 rounded-full", tone, status !== "connected" && "animate-pulse")} />
      {label}
    </span>
  );
}

function subscribeTheme(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => obs.disconnect();
}

function ThemeToggle() {
  const dark = useSyncExternalStore(subscribeTheme, () => document.documentElement.classList.contains("dark"), () => false);
  return (
    <button
      type="button"
      className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
      aria-label="Toggle dark mode"
      onClick={() => {
        const next = !dark;
        document.documentElement.classList.toggle("dark", next);
        try {
          localStorage.setItem("theme", next ? "dark" : "light");
        } catch {}
      }}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: me } = useMe();
  const { data: buildings } = useBuildings();
  const isAdmin = me?.user.role === "society_admin";
  const match = pathname.match(/^\/buildings\/(\d+)/);
  const currentId = match ? Number(match[1]) : null;

  async function logout() {
    await fetch("/session/logout", { method: "POST" });
    router.replace("/login");
  }

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Flame className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">Evacuation Command</p>
            <p className="truncate text-[11px] text-muted-foreground">{me?.society?.name ?? "…"}</p>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 text-sm">
          <Link href="/" className={cn("flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent", pathname === "/" && "bg-accent font-medium")}>
            <Building2 className="size-4" /> All buildings
          </Link>
          {isAdmin && (
            <Link href="/residents" className={cn("flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent", pathname === "/residents" && "bg-accent font-medium")}>
              <Users className="size-4" /> Residents
            </Link>
          )}
          {buildings?.map((b) => (
            <div key={b.id} className="mt-3">
              <Link href={`/buildings/${b.id}`} className="flex items-center justify-between gap-1 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground">
                <span className="truncate">{b.name}</span>
                {b.incident ? (
                  <Badge variant="fire" className="px-1 py-0 text-[10px]">{b.incident.kind === "drill" ? "DRILL" : "FIRE"}</Badge>
                ) : b.mode === "simulation" ? (
                  <Badge variant="muted" className="px-1 py-0 text-[10px]">SIM</Badge>
                ) : null}
              </Link>
              {currentId === b.id &&
                BUILDING_NAV.filter((n) => !n.admin || isAdmin).map((n) => {
                  const href = `/buildings/${b.id}${n.href}`;
                  const active = n.href === "" ? pathname === href : pathname.startsWith(href);
                  return (
                    <Link key={n.href} href={href} className={cn("flex items-center gap-2 rounded-md px-2 py-1.5 pl-4 hover:bg-accent", active && "bg-accent font-medium")}>
                      <n.icon className="size-4" /> {n.label}
                    </Link>
                  );
                })}
            </div>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t px-3 py-2">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium">{me?.user.name}</p>
            <p className="truncate text-[11px] text-muted-foreground">{me?.user.role.replace("_", " ")}</p>
          </div>
          <div className="flex items-center">
            <ThemeToggle />
            <button type="button" onClick={logout} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Sign out">
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b bg-background/85 px-4 py-2 backdrop-blur">
          <div className="flex min-w-0 items-center gap-2 md:hidden">
            <Flame className="size-4 text-primary" />
            <select
              className="max-w-[60vw] truncate rounded-md border bg-background px-2 py-1 text-sm"
              value={currentId ?? ""}
              onChange={(e) => router.push(e.target.value ? `/buildings/${e.target.value}` : "/")}
              aria-label="Building"
            >
              <option value="">All buildings</option>
              {buildings?.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
          <p className="hidden text-xs text-muted-foreground md:block">Not a certified life-safety system - always follow fire service instructions.</p>
          <div className="flex items-center gap-3">
            <ConnectionPill />
            <span className="md:hidden">
              <ThemeToggle />
            </span>
          </div>
        </header>
        {currentId != null && (
          <nav className="flex gap-1 overflow-x-auto border-b px-2 py-1 md:hidden">
            {BUILDING_NAV.filter((n) => !n.admin || isAdmin).map((n) => {
              const href = `/buildings/${currentId}${n.href}`;
              return (
                <Link key={n.href} href={href} className={cn("whitespace-nowrap rounded-md px-2 py-1 text-xs", pathname === href && "bg-accent font-medium")}>
                  {n.label}
                </Link>
              );
            })}
          </nav>
        )}
        <main className="flex-1 p-4">{children}</main>
      </div>
    </div>
  );
}
