import { create } from "zustand";

import type { Snapshot } from "@/lib/types";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

interface LiveState {
  status: ConnectionStatus;
  lastError: string | null;
  snapshots: Record<number, Snapshot>;
  receivedAt: Record<number, number>;
  droppedPayloads: number;
  setStatus: (s: ConnectionStatus, err?: string | null) => void;
  setSnapshot: (s: Snapshot) => void;
  dropPayload: () => void;
}

export const useLive = create<LiveState>((set) => ({
  status: "connecting",
  lastError: null,
  snapshots: {},
  receivedAt: {},
  droppedPayloads: 0,
  setStatus: (status, err = null) => set({ status, lastError: err }),
  setSnapshot: (s) =>
    set((st) => ({
      snapshots: { ...st.snapshots, [s.building_id]: s },
      receivedAt: { ...st.receivedAt, [s.building_id]: Date.now() },
    })),
  dropPayload: () => set((st) => ({ droppedPayloads: st.droppedPayloads + 1 })),
}));

/** Snapshot is stale if the socket is down or nothing arrived for this long (engine ticks at 1 Hz). */
export const STALE_AFTER_MS = 5000;

export function isStale(receivedAt: number | undefined, status: ConnectionStatus, now = Date.now()): boolean {
  if (status !== "connected") return true;
  if (!receivedAt) return true;
  return now - receivedAt > STALE_AFTER_MS;
}
