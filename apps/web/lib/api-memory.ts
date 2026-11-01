import { apiFetch } from "@/lib/api-rag";

/*
 * Cumulative memory: scrubbed lessons from resolved conversations, gated by
 * a human review queue. Pending rows change nothing; approved rows are what
 * future replies can retrieve.
 */

export type MemoryStatus = "pending" | "approved" | "rejected";

export interface Memory {
  id: string;
  channel_id: string;
  summary: string;
  outcome: string | null;
  facts: string[];
  status: MemoryStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryList {
  memories: Memory[];
  total: number;
  pending_count: number;
  enabled: boolean;
}

export interface MemoryPatch {
  status?: MemoryStatus;
  summary?: string;
  outcome?: string;
  facts?: string[];
}

export async function fetchMemories(
  status?: MemoryStatus | "all",
): Promise<MemoryList> {
  const qs = new URLSearchParams();
  if (status && status !== "all") qs.set("status", status);
  qs.set("limit", "200");
  return apiFetch(`/api/v1/memory?${qs.toString()}`);
}

export async function updateMemory(
  id: string,
  patch: MemoryPatch,
): Promise<Memory> {
  return apiFetch(`/api/v1/memory/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function fetchMemorySettings(): Promise<{ enabled: boolean }> {
  return apiFetch("/api/v1/memory/settings");
}

export async function updateMemorySettings(
  enabled: boolean,
): Promise<{ enabled: boolean }> {
  return apiFetch("/api/v1/memory/settings", {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}
