"use client";

import { adminFetch } from "@/lib/admin-api";

export interface BillingOverviewRow {
  tenant_id: string;
  email: string;
  plan: string;
  balance_cents: number;
  held_cents: number;
  total_cents: number;
  status: "ok" | "low" | "empty" | "debt";
}

export interface BillingLedgerEntry {
  id: string;
  kind: string;
  status: string;
  amount_cents: number;
  reserved_cents: number;
  balance_after_cents: number | null;
  model_id: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  idempotency_key: string | null;
  expires_at: string | null;
  settled_at: string | null;
  note: string | null;
  created_at: string | null;
}

export interface TenantBilling {
  tenant_id: string;
  email: string;
  plan: string;
  balance_cents: number;
  held_cents: number;
  total_cents: number;
  status: "ok" | "low" | "empty" | "debt";
  holds: BillingLedgerEntry[];
  ledger: BillingLedgerEntry[];
}

export interface WalletReconcileResult {
  tenant_id: string;
  applied: boolean;
  balance_cents: number;
  db_balance_cents: number;
  redis_balance_cents: number | null;
  previous_balance_cents: number | null;
  delta_cents: number | null;
  redis_synced: boolean | null;
  reliable: boolean;
  warning: string | null;
}

export async function fetchBillingOverview(): Promise<BillingOverviewRow[]> {
  return adminFetch<BillingOverviewRow[]>("/api/v1/admin/billing/overview");
}

export async function fetchTenantBilling(id: string): Promise<TenantBilling> {
  return adminFetch<TenantBilling>(`/api/v1/admin/tenants/${encodeURIComponent(id)}/billing`);
}

export async function reconcileWallet(
  id: string,
  dryRun: boolean,
): Promise<WalletReconcileResult> {
  return adminFetch<WalletReconcileResult>(`/api/v1/admin/tenants/${encodeURIComponent(id)}/resync-balance`, {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
}

export interface PlanFeatureSpec {
  key: string;
  label: string;
  description: string;
  default: boolean;
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

export interface PlanCreateInput {
  slug: string;
  name: string;
  description?: string | null;
  price_cents?: number;
  included_credit_cents?: number;
  max_channels?: number | null;
  max_messages_per_month?: number | null;
  features?: Record<string, boolean>;
  is_active?: boolean;
  sort_order?: number;
}

export async function fetchPlanFeatures(): Promise<PlanFeatureSpec[]> {
  return adminFetch<PlanFeatureSpec[]>("/api/v1/admin/plan-features");
}

export async function fetchPlans(): Promise<AdminPlan[]> {
  return adminFetch<AdminPlan[]>("/api/v1/admin/plans");
}

export async function createPlan(input: PlanCreateInput): Promise<AdminPlan> {
  return adminFetch<AdminPlan>("/api/v1/admin/plans", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updatePlan(id: string, input: Partial<PlanCreateInput>): Promise<AdminPlan> {
  return adminFetch<AdminPlan>(`/api/v1/admin/plans/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

// ── Per-tenant feature overrides ─────────────────────────────────────

export interface TenantEntitlements {
  plan_slug: string;
  plan_name: string;
  status: string;
  max_channels: number | null;
  max_messages_per_month: number | null;
  included_credit_cents: number;
  /** Effective flags after merging the tenant override over the plan. */
  features: Record<string, boolean>;
  /** The plan's raw baseline, so the UI can offer a true "reset". */
  plan_features: Record<string, boolean>;
  /** Only the keys this tenant overrides; empty means pure plan inheritance. */
  features_override: Record<string, boolean>;
  promo_active: boolean;
  granted_by: string | null;
  granted_until: string | null;
}

export interface TenantSubscriptionRow {
  id: string;
  tenant_id: string;
  plan_id: string;
  email: string | null;
  plan_slug: string | null;
  plan_name: string | null;
  status: string;
  granted_by: string | null;
  granted_until: string | null;
  features_override: Record<string, boolean>;
}

export async function fetchTenantEntitlements(tenantId: string): Promise<TenantEntitlements> {
  return adminFetch<TenantEntitlements>(
    `/api/v1/admin/tenants/${encodeURIComponent(tenantId)}/entitlements`,
  );
}

export async function fetchSpecialTenants(): Promise<TenantSubscriptionRow[]> {
  return adminFetch<TenantSubscriptionRow[]>("/api/v1/admin/tenants/special");
}

/**
 * Replace a tenant's overrides. `true` forces a feature on, `false` forces it
 * off; keys left out inherit the plan. Sending `{}` clears the tenant back to
 * pure plan inheritance and removes it from the Special list.
 */
export async function saveTenantFeatures(
  tenantId: string,
  features: Record<string, boolean>,
): Promise<TenantSubscriptionRow> {
  return adminFetch<TenantSubscriptionRow>(
    `/api/v1/admin/tenants/${encodeURIComponent(tenantId)}/features`,
    { method: "PUT", body: JSON.stringify({ features }) },
  );
}