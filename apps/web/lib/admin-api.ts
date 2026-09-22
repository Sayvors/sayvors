const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Auth transport: httpOnly cookie set by POST /api/v1/admin/login.
 * No token is ever exposed to JS. sessionStorage holds only a non-secret
 * "session active" hint so the UI knows to render the shell between loads;
 * the server is still the source of truth (401/403 clears it).
 */
const SESSION_KEY = "sayvors.admin.session";

/** Required on every cookie-authenticated admin request (CSRF guard). */
const CSRF_HEADERS = { "X-Requested-With": "XMLHttpRequest" } as const;

export function adminHasSession(): boolean {
  try {
    return window.sessionStorage.getItem(SESSION_KEY) === "1";
  } catch {
    return false;
  }
}

function adminMarkSession(): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, "1");
  } catch {
    /* private mode */
  }
}

export function adminClearSession(): void {
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* private mode */
  }
}

export async function adminLogin(password: string): Promise<number> {
  const res = await fetch(`${API}/api/v1/admin/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    let detail = `Login failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* keep default */ }
    throw new Error(detail);
  }
  const data = (await res.json()) as { expires_in_minutes: number };
  adminMarkSession();
  return data.expires_in_minutes;
}

export async function adminLogout(): Promise<void> {
  try {
    await fetch(`${API}/api/v1/admin/logout`, {
      method: "POST",
      credentials: "include",
      headers: CSRF_HEADERS,
    });
  } catch {
    /* best effort — clear the hint regardless */
  }
  adminClearSession();
}

/** Admin API call via cookie. 401/403 clears the session (layout logs out). */
export async function adminFetch<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...CSRF_HEADERS,
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 401 || res.status === 403) {
    adminClearSession();
    throw new Error("Admin session expired — log in again.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* keep default */ }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
