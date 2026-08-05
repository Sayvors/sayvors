const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="));
  return match ? match.split("=")[1] : null;
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const method = options.method || "GET";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  const csrfToken = getCsrfToken();
  if (csrfToken && ["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    headers["X-CSRF-Token"] = csrfToken;
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && path !== "/api/v1/auth/refresh") {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const newCsrf = getCsrfToken();
      if (newCsrf && ["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
        headers["X-CSRF-Token"] = newCsrf;
      }
      return fetch(`${API_URL}${path}`, { ...options, headers, credentials: "include" });
    }
    window.location.href = "/login";
  }

  return response;
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function logout() {
  window.location.href = "/login";
}
