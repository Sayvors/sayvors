import { apiFetch } from "@/lib/api-rag";

export type DeletionStatus = "none" | "pending" | "cancelled" | "completed";

export interface DeletionState {
  status: DeletionStatus;
  requested_at?: string | null;
  scheduled_for?: string | null;
  cancelled_at?: string | null;
  completed_at?: string | null;
}

export async function fetchDeletionState(): Promise<DeletionState> {
  return (await apiFetch("/api/v1/account/deletion")) as DeletionState;
}

export async function requestPersonalDataDeletion(): Promise<DeletionState> {
  return (await apiFetch("/api/v1/account/deletion", {
    method: "POST",
    body: JSON.stringify({ confirm: "DELETE" }),
  })) as DeletionState;
}

export async function cancelPersonalDataDeletion(): Promise<DeletionState> {
  return (await apiFetch("/api/v1/account/deletion", {
    method: "DELETE",
  })) as DeletionState;
}
