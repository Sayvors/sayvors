"use client";

import { apiFetch } from "./api-rag";

export const WHATSAPP_USAGE_PERIODS = [30, 90, 365] as const;
export type WhatsAppUsagePeriod = (typeof WHATSAPP_USAGE_PERIODS)[number];
export type FundingMode = "direct_client" | "shared_credit_line" | "platform_liable";
export type CostAvailability = "available" | "partial" | "unavailable" | "pending";
export type MetaSyncStatus = "synced" | "syncing" | "pending" | "error";

/** FastAPI may serialize Decimal values as strings; never coerce null to zero. */
export type SpendAmount = number | string | null;

export interface WhatsAppSpendTotal {
  funding_mode: FundingMode;
  volume: number;
  approximate_cost: SpendAmount;
  currency: string | null;
  cost_availability: CostAvailability;
  last_meta_sync_at: string | null;
}

export interface WhatsAppSpendBreakdownRow extends WhatsAppSpendTotal {
  waba_id?: string | null;
  waba_name?: string | null;
  phone?: string | null;
  category?: string | null;
}

export interface WhatsAppUsageResponse {
  used: number;
  limit: number | null;
  remaining: number | null;
  approximate_cost: SpendAmount;
  currency: string | null;
  cost_availability: CostAvailability;
  funding_mode: FundingMode;
  last_meta_sync_at: string | null;
  sync_status: MetaSyncStatus;
  totals: WhatsAppSpendTotal[];
  breakdowns: {
    by_waba: WhatsAppSpendBreakdownRow[];
    by_phone: WhatsAppSpendBreakdownRow[];
    by_category: WhatsAppSpendBreakdownRow[];
  };
}

export async function fetchWhatsAppUsage(
  days: WhatsAppUsagePeriod = 30,
): Promise<WhatsAppUsageResponse> {
  return apiFetch(`/api/v1/billing/whatsapp-usage?days=${days}`);
}
