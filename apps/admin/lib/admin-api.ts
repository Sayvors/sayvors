"use client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// The admin session lives in an httpOnly cookie set by the API
// (POST /api/v1/admin/login). JS can never read it, so there is no token
// storage here — session state is checked via GET /api/v1/admin/me.
// Every request must carry credentials (cross-origin :3001 → :8000) plus
// the X-Requested-With header the API's cookie CSRF check requires.
const ADMIN_HEADERS = { "X-Requested-With": "XMLHttpRequest" };

export async function checkAdminSession(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  try {
    const res = await fetch(`${API}/api/v1/admin/me`, {
      headers: { ...ADMIN_HEADERS },
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function adminLogin(password: string): Promise<{ expires_in_minutes: number }> {
  const res = await fetch(`${API}/api/v1/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...ADMIN_HEADERS },
    credentials: "include",
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(extractDetail(text, res.status));
  }
  return res.json();
}

export async function adminLogout(): Promise<void> {
  try {
    await fetch(`${API}/api/v1/admin/logout`, {
      method: "POST",
      headers: { ...ADMIN_HEADERS },
      credentials: "include",
    });
  } catch {
    /* clearing server state is best-effort; the cookie is httpOnly */
  }
}

export async function adminFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const res = await fetch(`${API}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...ADMIN_HEADERS,
        ...(options.headers as Record<string, string>),
      },
      signal: controller.signal,
    });
    if (res.status === 401 || res.status === 403) {
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
