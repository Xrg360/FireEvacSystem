"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { io, type Socket } from "socket.io-client";
import { toast } from "sonner";

import { SnapshotSchema } from "@/lib/schemas";
import type { Snapshot, SosRequest } from "@/lib/types";
import { useLive } from "./store";

export const API_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:5000";

const SocketContext = createContext<Socket | null>(null);

export function useSocket() {
  return useContext(SocketContext);
}

async function fetchToken(): Promise<string | null> {
  const res = await fetch("/session/token", { cache: "no-store" });
  if (!res.ok) return null;
  return ((await res.json()) as { token: string }).token;
}

export function SocketProvider({ children }: { children: ReactNode }) {
  const [socket, setSocket] = useState<Socket | null>(null);
  const qc = useQueryClient();
  const setStatus = useLive((s) => s.setStatus);
  const setSnapshot = useLive((s) => s.setSnapshot);
  const dropPayload = useLive((s) => s.dropPayload);

  useEffect(() => {
    const s = io(API_PUBLIC_URL, {
      transports: ["websocket", "polling"],
      // a fresh token on every (re)connect, so long sessions survive token expiry
      auth: (cb) => {
        fetchToken().then((token) => cb({ token }));
      },
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });
    s.on("connect", () => {
      setStatus("connected");
      setSocket(s);
    });
    s.on("disconnect", (reason) => setStatus("disconnected", reason));
    s.on("connect_error", (err) => setStatus("disconnected", err.message));
    s.on("snapshot", (raw: unknown) => {
      const parsed = SnapshotSchema.safeParse(raw);
      if (parsed.success) setSnapshot(parsed.data as unknown as Snapshot);
      else {
        dropPayload();
        console.warn("dropped malformed snapshot", parsed.error.issues.slice(0, 3));
      }
    });
    s.on("incident.updated", (d: { incident: { kind: string; status: string }; building_name: string }) => {
      const { kind, status } = d.incident;
      if (status === "evacuating") toast.error(`${kind === "drill" ? "Drill" : "FIRE"} - ${d.building_name}`, { description: "Residents are being alerted." });
      else toast.success(`${d.building_name}: ${status.replace("_", " ")}`);
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
    });
    s.on("sos.created", (d: SosRequest) => {
      toast.error(`SOS: ${d.user_name ?? "Resident"}${d.flat ? ` (${d.flat})` : ""}`, {
        description: `${d.kind}${d.note ? ` - ${d.note}` : ""}${d.stairs_ok ? "" : " · cannot use stairs"}`,
        duration: 20000,
      });
    });
    s.on("sensor.reading", (d: { triggered: boolean; reasons: string[] }) => {
      if (d.triggered && d.reasons?.length) toast.warning("Sensor alarm", { description: d.reasons.join(", ") });
      qc.invalidateQueries({ queryKey: ["sensors"] });
    });
    return () => {
      s.disconnect();
      setSocket(null);
    };
  }, [qc, setStatus, setSnapshot, dropPayload]);

  return <SocketContext.Provider value={socket}>{children}</SocketContext.Provider>;
}

/** Subscribe the shared socket to one building's room (re-subscribes after reconnects). */
export function useBuildingSubscription(buildingId: number | null) {
  const socket = useSocket();
  const setSnapshot = useLive((s) => s.setSnapshot);
  const subscribed = useRef<number | null>(null);

  useEffect(() => {
    if (!socket || buildingId == null) return;
    const subscribe = () => {
      socket.emit("subscribe", { building_id: buildingId }, (resp: { ok: boolean; snapshot?: unknown }) => {
        if (resp?.ok) {
          subscribed.current = buildingId;
          const parsed = resp.snapshot ? SnapshotSchema.safeParse(resp.snapshot) : null;
          if (parsed?.success) setSnapshot(parsed.data as unknown as Snapshot);
        }
      });
    };
    if (socket.connected) subscribe();
    socket.on("connect", subscribe);
    return () => {
      socket.off("connect", subscribe);
      socket.emit("unsubscribe");
      subscribed.current = null;
    };
  }, [socket, buildingId, setSnapshot]);
}
