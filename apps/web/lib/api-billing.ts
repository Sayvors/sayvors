"use client";

import { apiFetch } from "./api-rag";

export interface BillingProfile {
  id: string;
  user_id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  tax_id: string | null;
}

export interface PaymentMethod {
  id: string;
  user_id: string;
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name: string | null;
  is_default: boolean;
  provider: string;
  verified: boolean;
  expired: boolean;
}

export async function getBillingProfile(): Promise<BillingProfile | null> {
  return apiFetch("/api/v1/billing/profile");
}

export async function saveBillingProfile(
  data: Partial<Omit<BillingProfile, "id" | "user_id">>
): Promise<BillingProfile> {
  return apiFetch("/api/v1/billing/profile", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function listPaymentMethods(): Promise<PaymentMethod[]> {
  return apiFetch("/api/v1/billing/methods");
}

export async function addPaymentMethod(data: {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name?: string;
  is_default?: boolean;
  provider?: string;
  provider_token?: string;
}): Promise<PaymentMethod> {
  return apiFetch("/api/v1/billing/methods", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface GatewayToken {
  token: string;
  provider: string;
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name: string | null;
}

export async function tokenizeCard(data: {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name?: string;
}): Promise<GatewayToken> {
  return apiFetch("/api/v1/billing/gateway/tokenize", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface GatewayCharge {
  id: string;
  provider: string;
  status: string;
  amount_cents: number;
  currency: string;
  description: string | null;
}

export async function chargeCard(data: {
  token: string;
  amount_cents: number;
  currency?: string;
  description?: string;
}): Promise<GatewayCharge> {
  return apiFetch("/api/v1/billing/gateway/charge", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function setDefaultMethod(id: string): Promise<PaymentMethod> {
  return apiFetch(`/api/v1/billing/methods/${id}/default`, { method: "POST" });
}

export async function removePaymentMethod(id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/v1/billing/methods/${id}`, { method: "DELETE" });
}

export interface Budget {
  plan: string;
  balance_cents: number;
  balance_dollars: number;
  currency: string;
  credits_per_usd?: number;
  balance_credits?: number;
}

export async function getBudget(): Promise<Budget> {
  return apiFetch("/api/v1/billing/budget");
}

export interface BillingLedgerEntry {
  id: string;
  kind: string;
  status: string;
  amount_cents: number;
  reserved_cents: number;
  balance_after_cents: number | null;
  purpose: string | null;
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
  /** Full ledger row count, independent of the returned page. */
  total: number;
  holds: BillingLedgerEntry[];
  ledger: BillingLedgerEntry[];
}

export type LedgerSort = "newest" | "oldest" | "cost_high" | "cost_low";

export interface LedgerQuery {
  limit?: number;
  offset?: number;
  sort?: LedgerSort;
}

export async function getLedger(params: LedgerQuery = {}): Promise<TenantBilling> {
  const query = new URLSearchParams();
  if (params.limit != null) query.set("limit", String(params.limit));
  if (params.offset != null) query.set("offset", String(params.offset));
  if (params.sort != null) query.set("sort", params.sort);
  const suffix = query.toString();
  return apiFetch(`/api/v1/billing/ledger${suffix ? `?${suffix}` : ""}`);
}

export interface PlanFeatureSpec {
  key: string;
  label: string;
  description: string;
  default: boolean;
}

export interface WebPlan {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  price_cents: number;
  included_credit_cents: number;
  max_channels: number | null;
  max_messages_per_month: number | null;
  features: Record<string, boolean>;
  sort_order: number;
}

export interface Entitlements {
  plan_slug: string;
  plan_name: string;
  status: string;
  max_channels: number | null;
  max_messages_per_month: number | null;
  messages_used_this_month: number;
  messages_remaining: number | null;
  included_credit_cents: number;
  features: Record<string, boolean>;
  promo_active: boolean;
  granted_by: string | null;
  granted_until: string | null;
}

export async function getPlans(): Promise<WebPlan[]> {
  return apiFetch("/api/v1/billing/plans");
}

export async function getEntitlements(): Promise<Entitlements> {
  return apiFetch("/api/v1/billing/entitlements");
}

// ── Purchase requests (no payment gateway yet) ──────────────────────────

export type BillingRequestKind = "messages" | "channels" | "ai_credit" | "plan";

export interface BillingRequest {
  id: string;
  tenant_id: string;
  kind: BillingRequestKind;
  amount: number | null;
  plan_slug: string | null;
  note: string | null;
  status: "pending" | "approved" | "rejected";
  reviewed_by: string | null;
  reviewed_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export async function createBillingRequest(input: {
  kind: BillingRequestKind;
  amount?: number | null;
  plan_slug?: string | null;
  note?: string | null;
}): Promise<BillingRequest & { duplicate?: boolean }> {
  return apiFetch("/api/v1/billing/requests", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listBillingRequests(): Promise<BillingRequest[]> {
  const data = (await apiFetch("/api/v1/billing/requests")) as {
    items?: BillingRequest[];
  };
  return data?.items ?? [];
}
