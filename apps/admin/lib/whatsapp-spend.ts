"use client";

import { adminFetch } from "./admin-api";

export const WHATSAPP_SPEND_PERIODS = [30, 90, 365] as const;
export type WhatsAppSpendPeriod = (typeof WHATSAPP_SPEND_PERIODS)[number];
export type FundingMode = "direct_client" | "shared_credit_line" | "platform_liable";
export type CostAvailability = "available" | "partial" | "unavailable" | "pending";
export type MetaSyncStatus = "synced" | "syncing" | "pending" | "error";
export type SpendAmount = number | string | null;

export interface WhatsAppSpendTotal {
  funding_mode: FundingMode;
  volume: number;
  approximate_cost: SpendAmount;
  currency: string | null;
  cost_availability: CostAvailability;
  last_meta_sync_at: string | null;
}

export interface WhatsAppSpendRow extends WhatsAppSpendTotal {
  tenant_id: string;
  tenant_name: string | null;
  tenant_email?: string | null;
  waba_id: string;
  waba_name?: string | null;
  sync_status?: MetaSyncStatus;
}

export interface WhatsAppSpendResponse {
  days: WhatsAppSpendPeriod;
  items: WhatsAppSpendRow[];
  total: number;
  totals: WhatsAppSpendTotal[];
}

export interface CurrencySpendTotal {
  currency: string;
  approximateCost: number;
  volume: number;
}

export interface WhatsAppSpendSummary {
  deliveredVolume: number;
  directClientByCurrency: CurrencySpendTotal[];
  sayvorsPayableByCurrency: CurrencySpendTotal[];
  unavailableCostVolume: number;
  directClientUnavailableCostVolume: number;
  sayvorsPayableUnavailableCostVolume: number;
  partial: boolean;
  lastSyncAt: string | null;
}

export async function fetchAdminWhatsAppSpend(
  days: WhatsAppSpendPeriod = 30,
): Promise<WhatsAppSpendResponse> {
  return adminFetch(`/api/v1/admin/whatsapp-spend?days=${days}`);
}

function numericAmount(amount: SpendAmount): number | null {
  if (amount === null) return null;
  const value = Number(amount);
  return Number.isFinite(value) ? value : null;
}

function safeVolume(volume: number): number {
  return Number.isFinite(volume) ? Math.max(volume, 0) : 0;
}

/** Backend totals are authoritative when present; rows may be a display page. */
export function summarizeWhatsAppSpend(response: WhatsAppSpendResponse): WhatsAppSpendSummary {
  const source = response.totals.length > 0 ? response.totals : response.items;
  const direct = new Map<string, CurrencySpendTotal>();
  const payable = new Map<string, CurrencySpendTotal>();
  let deliveredVolume = 0;
  let unavailableCostVolume = 0;
  let directClientUnavailableCostVolume = 0;
  let sayvorsPayableUnavailableCostVolume = 0;
  let partial = false;
  let lastSyncAt: string | null = null;

  for (const row of source) {
    const volume = safeVolume(row.volume);
    deliveredVolume += volume;
    if (row.cost_availability !== "available") partial = true;
    if (row.last_meta_sync_at) {
      const timestamp = Date.parse(row.last_meta_sync_at);
      const latest = lastSyncAt ? Date.parse(lastSyncAt) : Number.NEGATIVE_INFINITY;
      if (Number.isFinite(timestamp) && timestamp > latest) lastSyncAt = row.last_meta_sync_at;
    }

    const amount = numericAmount(row.approximate_cost);
    const currency = row.currency?.trim().toUpperCase();
    if (amount === null || !currency || row.cost_availability === "unavailable" || row.cost_availability === "pending") {
      unavailableCostVolume += volume;
      if (row.funding_mode === "direct_client") directClientUnavailableCostVolume += volume;
      else sayvorsPayableUnavailableCostVolume += volume;
      continue;
    }
    const target = row.funding_mode === "direct_client" ? direct : payable;
    const current = target.get(currency) ?? { currency, approximateCost: 0, volume: 0 };
    current.approximateCost += amount;
    current.volume += volume;
    target.set(currency, current);
  }

  const sorted = (totals: Map<string, CurrencySpendTotal>) =>
    [...totals.values()].sort((a, b) => a.currency.localeCompare(b.currency));
  return {
    deliveredVolume,
    directClientByCurrency: sorted(direct),
    sayvorsPayableByCurrency: sorted(payable),
    unavailableCostVolume,
    directClientUnavailableCostVolume,
    sayvorsPayableUnavailableCostVolume,
    partial,
    lastSyncAt,
  };
}
