"use client";

/* Platform-admin API client. Separate auth from tenant sessions: the admin
 * session lives in an httpOnly cookie (path /api/v1/admin) set by POST
 * /api/v1/admin/login, and cookie-authenticated calls MUST carry
 * X-Requested-With (the backend rejects them without it).
 */

import { API_BASE } from "./api-base";

const ADMIN_HEADERS: Record<string, string> = {
  "Content-Type": "application/json",
  "X-Requested-With": "XMLHttpRequest",
};

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.text();
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.detail === "string") return parsed.detail;
    } catch {
      /* not JSON */
    }
    return body.slice(0, 300) || `Request failed (${res.status}).`;
  } catch {
    return `Request failed (${res.status}).`;
  }
}

export async function adminFetch(path: string, options: RequestInit = {}): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...ADMIN_HEADERS, ...(options.headers as Record<string, string>) },
    credentials: "include",
  });
  if (res.status === 204) return undefined;
  if (!res.ok) throw new Error(await readError(res));
  const text = await res.text();
  return text ? JSON.parse(text) : undefined;
}

export interface AdminPlan {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  price_cents: number;
  included_credit_cents: number;
  max_channels: number | null;
  max_messages_per_month: number | null;
  features: Record<string, boolean>;
  is_active: boolean;
  sort_order: number;
}

export interface PlanFeatureSpec {
  key: string;
  label: string;
  description: string;
  default: boolean;
}

export interface AdminTenant {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  plan: string;
}

export interface AdminSubscription {
  id: string;
  tenant_id: string;
  plan_id: string;
  plan_slug: string | null;
  plan_name: string | null;
  status: string;
  granted_by: string | null;
  granted_until: string | null;
}

export interface AdminEntitlements {
  plan_slug: string;
  plan_name: string;
  status: string;
  max_channels: number | null;
  max_messages_per_month: number | null;
  included_credit_cents: number;
  features: Record<string, boolean>;
  promo_active: boolean;
  granted_by: string | null;
  granted_until: string | null;
}

export async function adminLogin(username: string, password: string): Promise<void> {
  await adminFetch("/api/v1/admin/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function adminMe(): Promise<{ admin: boolean }> {
  return adminFetch("/api/v1/admin/me");
}

export async function adminLogout(): Promise<void> {
  await adminFetch("/api/v1/admin/logout", { method: "POST" });
}

export async function listPlanFeatures(): Promise<PlanFeatureSpec[]> {
  return adminFetch("/api/v1/admin/plan-features");
}

export async function listPlans(): Promise<AdminPlan[]> {
  return adminFetch("/api/v1/admin/plans");
}

export async function createPlan(body: Record<string, unknown>): Promise<AdminPlan> {
  return adminFetch("/api/v1/admin/plans", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updatePlan(id: string, body: Record<string, unknown>): Promise<AdminPlan> {
  return adminFetch(`/api/v1/admin/plans/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function searchTenants(q: string): Promise<{ total: number; items: AdminTenant[] }> {
  const params = new URLSearchParams({ search: q, limit: "10" });
  return adminFetch(`/api/v1/admin/tenants?${params.toString()}`);
}

export async function getSubscription(tenantId: string): Promise<AdminSubscription> {
  return adminFetch(`/api/v1/admin/tenants/${tenantId}/subscription`);
}

export async function getTenantEntitlements(tenantId: string): Promise<AdminEntitlements> {
  return adminFetch(`/api/v1/admin/tenants/${tenantId}/entitlements`);
}

export async function grantPlan(
  tenantId: string,
  planSlug: string,
  grantedUntil: string | null,
): Promise<AdminSubscription> {
  return adminFetch(`/api/v1/admin/tenants/${tenantId}/grant-plan`, {
    method: "POST",
    body: JSON.stringify({ plan_slug: planSlug, granted_until: grantedUntil }),
  });
}
