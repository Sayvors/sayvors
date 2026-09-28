"use client";

import { getAccessToken } from "./auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface AssistantStreamEvent {
  type: "step" | "delta" | "done" | "error";
  /** Stable id so a repeated step updates its row instead of appending. */
  id?: string;
  label?: string;
  detail?: string | null;
  text?: string;
  message?: string;
  grounded_in_rag?: boolean;
  citations?: Array<{ source?: string; kind?: string; detail?: string }>;
  model?: string;
}

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="));
  return match ? match.slice(match.indexOf("=") + 1) : null;
}

/**
 * Stream an Ask Sayvors answer: progress steps first, then the reply
 * token by token. Mirrors the review-engine stream client.
 */
export async function* streamAssistantChat(
  message: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal
): AsyncGenerator<AssistantStreamEvent, void, void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;

  const res = await fetch(`${API}/api/v1/assistant/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, history: history.slice(-8) }),
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
            yield JSON.parse(line.slice(5).trim()) as AssistantStreamEvent;
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
