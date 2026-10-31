"use client";

import { adminFetch } from "@/lib/admin-api";

export interface ASRProvider {
  provider: string;
  label: string;
  model: string | null;
  base_url: string | null;
  languages: string;
  enabled: boolean;
  active: boolean;
  has_key: boolean;
  updated_at: string | null;
  needs_key: boolean;
  default_model: string | null;
  models: string[];
  note: string | null;
  docs: string | null;
}

export interface ASROverview {
  providers: ASRProvider[];
  active_provider: string | null;
}

export interface ASRSaveInput {
  model?: string | null;
  base_url?: string | null;
  languages: string;
  enabled: boolean;
  active: boolean;
  /** Omit to keep the stored key; "" clears it. */
  api_key?: string | null;
}

export interface ASRTestResult {
  ok: boolean;
  latency_ms: number;
  detail: string;
}

export async function fetchASR(): Promise<ASROverview> {
  return adminFetch<ASROverview>("/api/v1/admin/asr");
}

export async function saveASR(
  provider: string,
  body: ASRSaveInput,
): Promise<ASRProvider> {
  return adminFetch<ASRProvider>(
    `/api/v1/admin/asr/${encodeURIComponent(provider)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

export async function testASR(provider: string): Promise<ASRTestResult> {
  return adminFetch<ASRTestResult>(
    `/api/v1/admin/asr/${encodeURIComponent(provider)}/test`,
    { method: "POST" },
  );
}
