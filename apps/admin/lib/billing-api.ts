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