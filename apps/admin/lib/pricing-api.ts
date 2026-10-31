"use client";

import { adminFetch } from "@/lib/admin-api";

export type PricingKind = "llm_input" | "llm_output" | "asr_minute" | "tts_kchar";

export interface PricingRateRow {
  kind: PricingKind;
  key: string;
  label: string;
  unit: string;
  unit_price_cents: number;
  default_cents: number;
  overridden: boolean;
}

export async function fetchPricing(): Promise<PricingRateRow[]> {
  return adminFetch<PricingRateRow[]>("/api/v1/admin/pricing");
}

export async function savePricing(
  kind: PricingKind,
  key: string,
  unitPriceCents: number,
): Promise<PricingRateRow> {
  return adminFetch<PricingRateRow>("/api/v1/admin/pricing", {
    method: "PUT",
    body: JSON.stringify({
      kind,
      key,
      unit_price_cents: unitPriceCents,
    }),
  });
}
