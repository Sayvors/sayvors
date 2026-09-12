"use client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "sayvors.admin.token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setAdminToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
  else window.sessionStorage.removeItem(TOKEN_KEY);
}

export async function adminLogin(password: string): Promise<{ access_token: string; expires_in_minutes: number }> {
  const res = await fetch(`${API}/api/v1/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(extractDetail(text, res.status));
  }
  return res.json();
}

export async function adminFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAdminToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const res = await fetch(`${API}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers as Record<string, string>),
      },
      signal: controller.signal,
    });
    if (res.status === 401 || res.status === 403) {
      setAdminToken(null);
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
      throw new Error("Admin session expired. Please log in again.");
    }
    if (!res.ok) throw new Error(extractDetail(await res.text().catch(() => ""), res.status));
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out. Try again.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function extractDetail(text: string, status: number): string {
  try {
    const data = JSON.parse(text);
    const detail = data?.detail;
    if (typeof detail === "string" && detail) return detail.slice(0, 200);
  } catch {
    /* not JSON */
  }
  return `Request failed (${status}).`;
}

export interface AdminOverview {
  users_total: number;
  users_verified: number;
  signups_last_7d: number;
  connections: number;
  last_synced_at: string | null;
  reviews_total: number;
  posts_total: number;
  posts_by_status: Record<string, number>;
  databanks_total: number;
  documents_total: number;
  outbox_pending: number;
  outbox_failed: number;
  ingest_failed: number;
}

export interface AdminTenant {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  email_verified: boolean;
  created_at: string | null;
  has_connection: boolean;
  listing_name: string | null;
  last_synced_at: string | null;
  reviews: number;
  posts: number;
  databanks: number;
}

export interface AdminTenantDetail extends AdminTenant {
  recent_reviews: {
    id: string;
    rating: number;
    text: string;
    reviewer: string | null;
    sentiment: string;
    replied: boolean;
    created_at: string | null;
  }[];
  recent_posts: {
    id: string;
    title: string;
    status: string;
    created_at: string | null;
  }[];
}
