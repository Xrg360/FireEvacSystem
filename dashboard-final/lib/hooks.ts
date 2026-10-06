"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import { isStale, useLive } from "@/lib/realtime/store";
import { SnapshotSchema } from "@/lib/schemas";
import type {
  Building,
  EventLogItem,
  Graph,
  Incident,
  IncidentMetrics,
  Me,
  Resident,
  Sensor,
  SignageItem,
  Snapshot,
  SosRequest,
} from "@/lib/types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me"), staleTime: 60_000 });

export const useBuildings = () =>
  useQuery({ queryKey: ["buildings"], queryFn: async () => (await api.get<{ items: Building[] }>("/buildings")).items, refetchInterval: 15_000 });

export const useBuilding = (id: number) =>
  useQuery({ queryKey: ["buildings", id], queryFn: () => api.get<Building>(`/buildings/${id}`), refetchInterval: 10_000 });

export const useGraph = (id: number, version?: number) =>
  useQuery({
    queryKey: ["graph", id, version ?? "latest"],
    queryFn: () => api.get<Graph>(`/buildings/${id}/graph`),
    staleTime: Infinity,
    enabled: id > 0,
  });

export const useIncidents = (buildingId: number) =>
  useQuery({
    queryKey: ["incidents", buildingId],
    queryFn: async () => (await api.get<{ items: (Incident & { metrics: IncidentMetrics | null })[] }>(`/buildings/${buildingId}/incidents`)).items,
  });

export interface IncidentDetail extends Incident {
  metrics: IncidentMetrics | null;
  participants: {
    device_id: string;
    user_id: number | null;
    name: string | null;
    flat: string | null;
    phone: string | null;
    stairs_ok: boolean;
    status: string;
    notified_at: string | null;
    acknowledged_at: string | null;
    safe_at: string | null;
    assigned_exit_id: number | null;
  }[];
}

export const useIncident = (id: number) =>
  useQuery({ queryKey: ["incidents", "detail", id], queryFn: () => api.get<IncidentDetail>(`/incidents/${id}`) });

export const useIncidentEvents = (id: number, types?: string) =>
  useQuery({
    queryKey: ["incidents", "events", id, types],
    queryFn: () => api.get<{ items: EventLogItem[]; started_at: string | null; ended_at: string | null }>(
      `/incidents/${id}/events?limit=10000${types ? `&types=${types}` : ""}`,
    ),
  });

export const useSensors = (buildingId: number) =>
  useQuery({ queryKey: ["sensors", buildingId], queryFn: async () => (await api.get<{ items: Sensor[] }>(`/buildings/${buildingId}/sensors`)).items, refetchInterval: 10_000 });

export const useSensorReadings = (sensorId: number | null) =>
  useQuery({
    queryKey: ["sensors", "readings", sensorId],
    enabled: sensorId != null,
    queryFn: async () => (await api.get<{ items: { ts: string; smoke: number | null; temperature_c: number | null }[] }>(`/sensors/${sensorId}/readings?limit=120`)).items,
    refetchInterval: 5000,
  });

export const useResidents = (status?: string) =>
  useQuery({
    queryKey: ["residents", status ?? "all"],
    queryFn: async () => (await api.get<{ items: Resident[] }>(`/residents${status ? `?status=${status}` : ""}`)).items,
  });

export const useSignage = (buildingId: number) =>
  useQuery({ queryKey: ["signage", buildingId], queryFn: async () => (await api.get<{ items: SignageItem[] }>(`/buildings/${buildingId}/signage`)).items });

export const useSos = (buildingId: number) =>
  useQuery({ queryKey: ["sos", buildingId], queryFn: async () => (await api.get<{ items: SosRequest[] }>(`/buildings/${buildingId}/sos`)).items });

/** Live snapshot from the socket, seeded by REST, plus staleness that updates every second. */
export function useLiveSnapshot(buildingId: number): { snapshot: Snapshot | undefined; stale: boolean; ageMs: number | null } {
  const snapshot = useLive((s) => s.snapshots[buildingId]);
  const receivedAt = useLive((s) => s.receivedAt[buildingId]);
  const status = useLive((s) => s.status);
  const setSnapshot = useLive((s) => s.setSnapshot);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (snapshot) return;
    let cancelled = false;
    api
      .get<unknown>(`/buildings/${buildingId}/live`)
      .then((raw) => {
        const parsed = SnapshotSchema.safeParse(raw);
        if (!cancelled && parsed.success) setSnapshot(parsed.data as unknown as Snapshot);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [buildingId, snapshot, setSnapshot]);

  return { snapshot, stale: isStale(receivedAt, status, now), ageMs: receivedAt ? now - receivedAt : null };
}
