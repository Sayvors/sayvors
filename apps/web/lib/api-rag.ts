"use client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("sayvors_access_token");
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("sayvors_refresh_token");
}

function setTokens(access: string, refresh: string) {
  localStorage.setItem("sayvors_access_token", access);
  localStorage.setItem("sayvors_refresh_token", refresh);
}

function clearAuth() {
  localStorage.removeItem("sayvors_access_token");
  localStorage.removeItem("sayvors_refresh_token");
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  try {
    const res = await fetch(`${API}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<any> {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...(options.headers as Record<string, string>),
    },
  });

  if (res.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const retryRes = await fetch(`${API}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
          ...(options.headers as Record<string, string>),
        },
      });
      if (!retryRes.ok) throw new Error(await retryRes.text());
      return retryRes.json();
    }
    clearAuth();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadFile(databankId: string, file: File): Promise<any> {
  const token = getAccessToken();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API}/api/v1/rag/databanks/${databankId}/documents`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listDatabanks(): Promise<any> {
  return apiFetch("/api/v1/rag/databanks");
}

export async function createDatabank(data: { name: string; description?: string; accent_color?: string }): Promise<any> {
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

export async function deleteDocument(databankId: string, docId: string): Promise<void> {
  await apiFetch(`/api/v1/rag/databanks/${databankId}/documents/${docId}`, { method: "DELETE" });
}
