"use client";

import { apiFetch } from "./api-rag";

export interface UsageModelRow {
  model: string;
  api_model: string;
  calls: number;
  total_tokens: number;
  avg_latency_ms: number;
}

export interface UsagePurposeRow {
  purpose: string;
  calls: number;
  total_tokens: number;
}

export interface UsageDayRow {
  day: string;
  total_tokens: number;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  avg_latency_ms: number;
}

export interface UsageSummary {
  days: number;
  totals: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    avg_latency_ms: number;
  };
  by_model: UsageModelRow[];
  by_purpose: UsagePurposeRow[];
  daily: UsageDayRow[];
}

export async function getUsageSummary(days = 30): Promise<UsageSummary> {
  return apiFetch(`/api/v1/llm/usage/summary?days=${days}`);
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}
