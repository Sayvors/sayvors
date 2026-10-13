"use client";

import { API_BASE } from "./api-base";
import { getAccessToken, refreshSession } from "./auth-context";
import { ensureCsrfToken, getCsrfToken, isCsrfFailure, prefetchCsrfToken } from "./csrf";

const API = API_BASE;

/**
 * Turn an error response into something a person can act on. `res.text()` was
 * dumped raw, so a FastAPI rejection surfaced as `{"detail":"CSRF validation
 * failed"}` in the middle of a form -- true, but it read like gibberish and
 * named a protection the user never triggered.
 */
async function readError(res: Response): Promise<string> {
  let body: string;
  try {
    body = await res.text();
  } catch {
    return `Request failed (${res.status}).`;
  }
  let detail: string | null = null;
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed?.detail === "string") detail = parsed.detail;
    else if (Array.isArray(parsed?.detail) && typeof parsed.detail[0]?.msg === "string") {
      // Pydantic validation errors: surface the field, not the object dump.
      const d = parsed.detail[0];
      detail = d.loc?.length ? `${String(d.loc[1] ?? d.loc[0])}: ${d.msg}` : d.msg;
    }
  } catch {
    /* not JSON */
  }
  if (!detail) return body.slice(0, 300) || `Request failed (${res.status}).`;
  if (detail === "CSRF validation failed") {
    return "Your session expired mid-request and could not be renewed. Reload the page and try again.";
  }
  return detail;
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

/**
 * Explain a CSRF rejection using facts only the browser knows. "Your session
 * expired, reload the page" is unactionable when the session is fine and the
 * real fault is that the cookie is not being attached to the request.
 */
function csrfDiagnosis(path: string): string {
  if (typeof window === "undefined") return "CSRF check failed.";
  const cookie = getCsrfToken();
  const crossSite = new URL(API || window.location.origin, window.location.href).origin !== window.location.origin;
  return [
    "Your security token was not accepted.",
    `page ${window.location.origin} · api ${API || "(same origin)"} · ${
      crossSite ? "CROSS-SITE request" : "same-origin"
    } · cookie ${cookie ? "readable" : "MISSING"}`,
    `on POST ${path}.`,
    crossSite
      ? "Over plain http a cross-site cookie can never be sent, so browse the dev server origin directly."
      : "Reload the page to re-issue the cookie.",
  ].join(" ");
}

export async function apiFetch(path: string, options: RequestInit = {}, timeoutMs = 60000): Promise<any> {
  const method = (options.method || "GET").toUpperCase();
  const isForm = options.body instanceof FormData;
  const isWrite = !["GET", "HEAD", "OPTIONS"].includes(method);

  // Mint a token up front for writes when the jar is empty. Without this the
  // header was simply omitted and the request was guaranteed to 403.
  if (isWrite) await prefetchCsrfToken();

  const headers = {
    ...buildHeaders(isForm),
    ...(options.headers as Record<string, string>),
  };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const doFetch = (hdrs: Record<string, string>) =>
    fetch(`${API}${path}`, {
      ...options,
      headers: hdrs,
      credentials: "include",
      signal: options.signal ?? controller.signal,
    });

  try {
    let res = await doFetch(headers);

    // One self-heal: a stale or missing token is recoverable, and the CSRF
    // middleware answers before the route, so a rejected write never had a
    // side effect and replaying it cannot duplicate one.
    if (isWrite && isCsrfFailure(res)) {
      const fresh = await ensureCsrfToken();
      if (fresh) {
        res = await doFetch({
          ...buildHeaders(isForm),
          ...(options.headers as Record<string, string>),
          "X-CSRF-Token": fresh,
        });
      }
      // Still rejected. Report what the browser actually did rather than a
      // generic "reload the page" that cannot help: the usual cause is the
      // request being cross-site, so the cookie exists but is never attached.
      if (isCsrfFailure(res)) {
        throw new Error(csrfDiagnosis(path));
      }
    }

    // A proxy error page (Cloudflare tunnel down, nginx, etc.) arrives as
    // HTML with any status — never dump its markup into a UI error box.
    if ((res.headers.get("content-type") || "").includes("text/html")) {
      throw new Error(
        `The server is unreachable right now (gateway error ${res.status}) — try again in a minute.`,
      );
    }

    if (res.status === 401 && path !== "/api/v1/auth/refresh") {
      const refreshed = await refreshSession();
      if (refreshed) {
        const retryHeaders = { ...buildHeaders(isForm), ...(options.headers as Record<string, string>) };
        let retryRes = await doFetch(retryHeaders);
        if (isWrite && isCsrfFailure(retryRes)) {
          const fresh = await ensureCsrfToken();
          if (fresh) retryRes = await doFetch({ ...retryHeaders, "X-CSRF-Token": fresh });
        }
        if ((retryRes.headers.get("content-type") || "").includes("text/html")) {
          throw new Error(
            `The server is unreachable right now (gateway error ${retryRes.status}) — try again in a minute.`,
          );
        }
        if (!retryRes.ok) throw new Error(await readError(retryRes));
        if (retryRes.status === 204) return undefined;
        return retryRes.json();
      }
      // Public pages must not bounce: auth pages would reload-loop, and /invite
      // visitors are anonymous by definition (they have no session yet).
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/signup") && !window.location.pathname.startsWith("/forgot-password") && !window.location.pathname.startsWith("/reset-password") && !window.location.pathname.startsWith("/verify-email") && !window.location.pathname.startsWith("/verify-otp") && !window.location.pathname.startsWith("/invite")) {
        window.location.href = "/login";
      }
      throw new Error("Unauthorized");
    }

    if (!res.ok) throw new Error(await readError(res));
    if (res.status === 204) return undefined;
    return res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out — the server took too long. Try again.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/* ── Types ──────────────────────────────────────────── */

export interface DatabankDoc {
  id: string;
  name?: string;
  filename?: string;
  file_type?: string;
  file_size?: number;
  status?: string;
}

/* ── Databank CRUD ──────────────────────────────────── */

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

export async function retryDocuments(databankId: string, documentIds?: string[]): Promise<{ queued: number }> {
  return apiFetch(`/api/v1/rag/databanks/${databankId}/retry`, {
    method: "POST",
    body: JSON.stringify(documentIds ? { document_ids: documentIds } : {}),
  });
}

export interface DocumentPreview {
  kind: "table" | "text";
  filename: string;
  file_type?: string;
  status?: string;
  columns?: string[];
  rows?: Array<Record<string, string>>;
  chunks?: string[];
  total: number;
  page: number;
  page_size: number;
}

export async function previewDocument(
  databankId: string,
  docId: string,
  page = 1,
  pageSize = 25
): Promise<DocumentPreview> {
  return apiFetch(
    `/api/v1/rag/databanks/${databankId}/documents/${docId}/preview?page=${page}&page_size=${pageSize}`
  );
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
  }, 300000); // agentic RAG can take minutes
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

/* ── CSV Data ─────────────────────────────────────── */

export interface CSVUpload {
  id: string;
  filename: string;
  column_names: string[] | null;
  row_count: number;
  purpose: string | null;
  created_at?: string;
}

export interface CSVRow {
  id: string;
  row_index: number;
  data: Record<string, unknown>;
}

export async function uploadCSV(file: File, purpose?: string): Promise<CSVUpload> {
  const form = new FormData();
  form.append("file", file);
  if (purpose) form.append("purpose", purpose);
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch(`${API}/api/v1/csv/upload`, {
    method: "POST",
    headers,
    body: form,
    credentials: "include",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listCSVUploads(): Promise<CSVUpload[]> {
  return apiFetch("/api/v1/csv/uploads");
}

export async function deleteCSVUpload(id: string): Promise<void> {
  await apiFetch(`/api/v1/csv/uploads/${id}`, { method: "DELETE" });
}

export async function searchCSVRows(
  query: string,
  opts?: { upload_id?: string; purpose?: string; limit?: number }
): Promise<{ rows: CSVRow[]; total_matches: number }> {
  return apiFetch("/api/v1/csv/search", {
    method: "POST",
    body: JSON.stringify({ query, ...opts }),
  });
}

export async function getCSVRowsPaginated(
  uploadId: string,
  page: number,
  pageSize: number
): Promise<{ rows: CSVRow[]; total: number; page: number; page_size: number }> {
  return apiFetch(`/api/v1/csv/uploads/${uploadId}/rows?page=${page}&page_size=${pageSize}`);
}
