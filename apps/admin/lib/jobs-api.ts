"use client";

import { adminFetch } from "@/lib/admin-api";

export interface AdminJob {
  id: string;
  tenant_id: string;
  job_type: string;
  lane: string;
  status: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  last_error: string | null;
  subject_type: string | null;
  subject_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export async function fetchAdminJobs(params: {
  status?: string;
  lane?: string;
  tenant_id?: string;
  limit?: number;
}): Promise<AdminJob[]> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.lane) qs.set("lane", params.lane);
  if (params.tenant_id) qs.set("tenant_id", params.tenant_id);
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : "";
  return adminFetch<AdminJob[]>(`/api/v1/admin/jobs${suffix}`);
}

export async function fetchAdminJob(id: string): Promise<AdminJob> {
  return adminFetch<AdminJob>(`/api/v1/admin/jobs/${encodeURIComponent(id)}`);
}

export async function replayAdminJob(id: string): Promise<AdminJob> {
  return adminFetch<AdminJob>(`/api/v1/admin/jobs/${encodeURIComponent(id)}/replay`, { method: "POST" });
}

export async function cancelAdminJob(id: string): Promise<AdminJob> {
  return adminFetch<AdminJob>(`/api/v1/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}