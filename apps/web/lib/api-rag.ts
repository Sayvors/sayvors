"use client";

import { getAccessToken, setAccessToken } from "./auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="));
  return match ? match.split("=")[1] : null;
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${API}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.access_token) setAccessToken(data.access_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

function buildHeaders(isForm = false): Record<string, string> {
  const headers: Record<string, string> = {};
  if (!isForm) headers["Content-Type"] = "application/json";
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<any> {
  const method = options.method || "GET";
  const isForm = options.body instanceof FormData;
  const headers = {
    ...buildHeaders(isForm),
    ...(options.headers as Record<string, string>),
  };

  const res = await fetch(`${API}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (res.status === 401 && path !== "/api/v1/auth/refresh") {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retryHeaders = { ...buildHeaders(isForm), ...(options.headers as Record<string, string>) };
      const retryRes = await fetch(`${API}${path}`, { ...options, headers: retryHeaders, credentials: "include" });
      if (!retryRes.ok) throw new Error(await retryRes.text());
      return retryRes.json();
    }
    // Don't redirect if already on an auth page — prevents infinite reload loop
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/signup") && !window.location.pathname.startsWith("/forgot-password") && !window.location.pathname.startsWith("/reset-password") && !window.location.pathname.startsWith("/verify-email") && !window.location.pathname.startsWith("/verify-otp")) {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadFile(databankId: string, file: File): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch(`${API}/api/v1/rag/databanks/${databankId}/documents`, {
    method: "POST",
    headers,
    body: form,
    credentials: "include",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listDatabanks(): Promise<any> {
  return apiFetch("/api/v1/rag/databanks");
}

export async function createDatabank(data: {
  name: string;
  description?: string;
  accent_color?: string;
  sourceType?: string;
  sourceConfig?: { files?: string[]; crawlerUrl?: string; crawlerDepth?: number };
}): Promise<any> {
  return apiFetch("/api/v1/rag/databanks", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function deleteDatabank(id: string): Promise<void> {
  await apiFetch(`/api/v1/rag/databanks/${id}`, { method: "DELETE" });
}

export async function listDocuments(databankId: string): Promise<any> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/documents`);
}

export async function scrapeUrl(databankId: string, url: string, crawlMode: string, maxPages?: number): Promise<any> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/scrape`, {
    method: "POST",
    body: JSON.stringify({ url, crawl_mode: crawlMode, max_pages: maxPages }),
  });
}

export async function processPending(databankId: string): Promise<any> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/process`, { method: "POST" });
}

export async function processDocument(databankId: string, docId: string): Promise<any> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/documents/${docId}/process`, { method: "POST" });
}

export async function listJobs(): Promise<any> {
  return apiFetch("/api/v1/rag/jobs");
}

export async function searchRag(databankId: string, query: string, topK?: number): Promise<any> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/search`, {
    method: "POST",
    body: JSON.stringify({ query, top_k: topK ?? 5 }),
  });
}

export interface AskTraceStep {
  step: number;
  thought: string;
  tool: string | null;
  args: Record<string, unknown>;
  ms: number;
  observation: string;
}

export interface AskCitation {
  source: string;
  kind: string;
  detail: string;
}

export interface AskResponse {
  answer: string;
  citations: AskCitation[];
  trace: AskTraceStep[];
  steps_used: number;
  model: string;
}

export async function askDatabank(databankId: string, question: string): Promise<AskResponse> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/ask`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function deleteDocument(databankId: string, docId: string): Promise<void> {
  await apiFetch(`/api/v1/rag/databanks/${databankId}/documents/${docId}`, { method: "DELETE" });
}

/* ── Live database sources ─────────────────────────── */

export interface DatabaseConnection {
  db_type: "postgres" | "mysql";
  host: string;
  port?: number | null;
  database: string;
  username: string;
  password?: string;
}

export interface DatabaseSource extends DatabaseConnection {
  id: string;
  name: string;
  created_at: string;
}

export interface TablePreview {
  table: string;
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
}

export interface QueryResult {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
}

export async function testDatabaseSource(
  databankId: string,
  conn: DatabaseConnection
): Promise<{ ok: boolean; version?: string | null; error?: string | null }> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/sources/test`, {
    method: "POST",
    body: JSON.stringify(conn),
  });
}

export async function saveDatabaseSource(
  databankId: string,
  conn: DatabaseConnection & { name: string }
): Promise<DatabaseSource> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/sources`, {
    method: "POST",
    body: JSON.stringify(conn),
  });
}

export async function listDatabaseSources(databankId: string): Promise<{ sources: DatabaseSource[]; total: number }> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/sources`);
}

export async function deleteDatabaseSource(databankId: string, sourceId: string): Promise<void> {
  await apiFetch(`/api/v1/rag/databanks/${databankId}/sources/${sourceId}`, { method: "DELETE" });
}

export async function fetchSourceSchema(
  databankId: string,
  sourceId: string
): Promise<{ source_id: string; tables: { name: string; columns: number }[] }> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/sources/${sourceId}/schema`);
}

export async function previewSourceTable(
  databankId: string,
  sourceId: string,
  table: string,
  limit = 20
): Promise<TablePreview> {
  return apiFetch(
    `/api/v1/rag/databanks/${databankId}/sources/${sourceId}/tables/${encodeURIComponent(table)}?limit=${limit}`
  );
}

export async function runSourceQuery(
  databankId: string,
  sourceId: string,
  sql: string,
  limit = 200
): Promise<QueryResult> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/sources/${sourceId}/query`, {
    method: "POST",
    body: JSON.stringify({ sql, limit }),
  });
}

export async function ingestSourceQuery(
  databankId: string,
  sourceId: string,
  sql: string,
  name?: string,
  limit = 500
): Promise<unknown> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/sources/${sourceId}/ingest`, {
    method: "POST",
    body: JSON.stringify({ sql, name, limit }),
  });
}
