"use client";

import { getAccessToken } from "./auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ReviewEngineInput {
  review_text: string;
  rating: number;
  reviewer_name?: string;
  review_id?: string;
  channel?: string;
  channel_id?: string;
  model?: string;
  databank_id?: string;
}

export interface StreamEvent {
  step: string;
  message?: string;
  progress?: number;
  model?: string;
  model_source?: string;
  analysis?: Record<string, unknown>;
  issues?: Array<{ key: string; label: string; detail: string; keywords: string[] }>;
  strategy?: { id?: string; strategy_id?: string; name: string; reason: string; priority?: number; conditional?: boolean; condition_note?: string | null };
  requirements?: string[];
  tier?: { label: string; max_sentences: number; max_words: number; min_words: number };
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  bank_id?: string | null;
  need?: string;
  query?: string;
  fulfillment?: Array<{ strategy_id: string; strategy: string; status: string; reason: string; evidence: string }>;
  claims?: Array<{ claim: string; kind: string; status: string; source: string }>;
  relevance?: { verdict: string; reason: string; evidence: string; matched_terms: string[] };
  checks?: Record<string, boolean>;
  validation_issues?: string[];
  response?: {
    response_text: string;
    strategies_used: string[];
    validation: { passed: boolean; checks: Record<string, boolean>; issues: string[]; regenerated: boolean; strategy_fulfillment?: Array<{ strategy_id: string; strategy: string; status: string; reason: string; evidence: string }> };
    analysis: Record<string, unknown>;
    model: string;
    latency_ms: number;
    log_id: string;
    status?: string;
    relevance?: { verdict: string; reason: string; evidence: string; matched_terms: string[] };
  };
}

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="));
  return match ? match.split("=")[1] : null;
}

export async function* streamReviewReply(
  input: ReviewEngineInput,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent, void, void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;

  const res = await fetch(`${API}/api/v1/review-engine/generate-stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ channel: "google_review", ...input }),
    credentials: "include",
    signal,
  });
  if (!res.ok) throw new Error(await res.text());
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (line.startsWith("data:")) {
          try {
            yield JSON.parse(line.slice(5).trim()) as StreamEvent;
          } catch {
            // skip malformed chunk
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export interface EngineLog {
  id: string;
  review_text?: string;
  rating?: number;
  reviewer_name?: string;
  generated_response?: string;
  status?: string;
  model?: string;
  latency_ms?: number;
  created_at?: string;
}

export async function listEngineLogs(limit = 10): Promise<{ logs: EngineLog[] }> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API}/api/v1/review-engine/logs?limit=${limit}`, {
    headers,
    credentials: "include",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
