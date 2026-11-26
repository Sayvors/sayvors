"use client";

import { apiFetch } from "@/lib/api-rag";

export type AiVisibilityOverview = {
  completed_runs: number;
  mention_rate: number | null;
  citation_rate: number | null;
  recommendation_rate: number | null;
  active_prompts: number;
  covered_prompts: number;
  prompt_coverage: number | null;
  failed_runs: number;
  insufficient_runs: number;
  source_count: number;
  validated_claim_count: number;
};

export type AiVisibilityPrompt = {
  id: string;
  channel_id: string;
  title: string;
  prompt_text: string;
  intent: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AiVisibilitySource = {
  id: string;
  label: string;
  position: number;
  url: string;
  title: string | null;
  snippet: string | null;
  excerpt: string | null;
  fetch_error: string | null;
};

export type AiVisibilityClaim = {
  claim: string;
  quote: string;
  source_ids: string[];
  status: "supported" | "contradicted" | "unsupported";
};

export type AiVisibilityAction = {
  priority: "P0" | "P1" | "P2";
  category: string;
  title: string;
  rationale: string;
  deep_link: string;
  effort: "low" | "medium" | "high";
  evidence: Record<string, unknown>;
};

export type AiVisibilityRun = {
  id: string;
  channel_id: string;
  prompt_id: string;
  prompt_snapshot: string;
  locale: string;
  research_depth: string;
  status: string;
  job_id: string | null;
  validation_status: string;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type AiVisibilityRunDetail = AiVisibilityRun & {
  answer_text: string | null;
  mentioned: boolean | null;
  cited: boolean | null;
  recommended: boolean | null;
  incorrect: boolean | null;
  evidence_coverage: Record<string, unknown>;
  competitor_mentions: Array<{ name: string; quote: string; source_ids: string[] }>;
  claims: AiVisibilityClaim[];
  actions: AiVisibilityAction[];
  sources: AiVisibilitySource[];
  completed_at: string | null;
};

export type AiVisibilityRunListItem = {
  id: string;
  channel_id: string;
  prompt_id: string;
  prompt_title: string;
  status: string;
  mentioned: boolean | null;
  cited: boolean | null;
  recommended: boolean | null;
  incorrect: boolean | null;
  source_count: number;
  validation_status: string;
  created_at: string;
  completed_at: string | null;
};

function params(values: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, String(value));
  }
  return query.toString();
}

export const fetchOverview = (channelId: string, days: number) =>
  apiFetch(`/api/v1/ai-visibility/overview?${params({ channel_id: channelId, days })}`) as Promise<AiVisibilityOverview>;

export const fetchPrompts = (channelId: string, includeArchived = false) =>
  apiFetch(`/api/v1/ai-visibility/prompts?${params({ channel_id: channelId, include_archived: includeArchived })}`) as Promise<{ items: AiVisibilityPrompt[] }>;

export const createPrompt = (body: Omit<AiVisibilityPrompt, "id" | "is_active" | "created_at" | "updated_at">) =>
  apiFetch("/api/v1/ai-visibility/prompts", { method: "POST", body: JSON.stringify(body) }) as Promise<AiVisibilityPrompt>;

export const updatePrompt = (id: string, body: Partial<Pick<AiVisibilityPrompt, "title" | "prompt_text" | "intent" | "is_active">>) =>
  apiFetch(`/api/v1/ai-visibility/prompts/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }) as Promise<AiVisibilityPrompt>;

export const deletePrompt = (id: string) =>
  apiFetch(`/api/v1/ai-visibility/prompts/${encodeURIComponent(id)}`, { method: "DELETE" }) as Promise<void>;

export const createRun = (body: {
  channel_id: string;
  prompt_id: string;
  depth?: "quick" | "deep";
}) =>
  apiFetch("/api/v1/ai-visibility/runs", {
    method: "POST",
    body: JSON.stringify(body),
  }) as Promise<AiVisibilityRun>;

export const fetchRun = (id: string) =>
  apiFetch(`/api/v1/ai-visibility/runs/${encodeURIComponent(id)}`) as Promise<AiVisibilityRunDetail>;

export const fetchRuns = (channelId: string, options: { status?: string; promptId?: string; limit?: number; offset?: number } = {}) =>
  apiFetch(`/api/v1/ai-visibility/runs?${params({
    channel_id: channelId, status: options.status, prompt_id: options.promptId,
    limit: options.limit, offset: options.offset,
  })}`) as Promise<{ items: AiVisibilityRunListItem[]; total: number }>;

export const retryRun = (id: string) =>
  apiFetch(`/api/v1/ai-visibility/runs/${encodeURIComponent(id)}/retry`, { method: "POST" }) as Promise<AiVisibilityRun>;

export const deleteRun = (id: string) =>
  apiFetch(`/api/v1/ai-visibility/runs/${encodeURIComponent(id)}`, { method: "DELETE" }) as Promise<void>;

export const clearRuns = (channelId: string) =>
  apiFetch(`/api/v1/ai-visibility/runs?${params({ channel_id: channelId })}`, {
    method: "DELETE",
  }) as Promise<void>;
