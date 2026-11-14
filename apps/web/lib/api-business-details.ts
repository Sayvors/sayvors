"use client";

import { apiFetch } from "./api-rag";

export interface BusinessDetailsGoogle {
  name: string;
  address: string;
  website: string;
  categories: Record<string, unknown>;
  hours: Record<string, unknown>;
  services: unknown[];
  special_hours: unknown[];
}

export interface BusinessDetailsUser {
  name: string | null;
  categories: Record<string, unknown>;
  services: unknown[];
  hours: Record<string, unknown>;
  special_hours: unknown[];
  source: string;
  updated_at: string | null;
}

export interface BusinessDetailsOut {
  listing_id: string;
  google: BusinessDetailsGoogle;
  user: BusinessDetailsUser | null;
}

export interface BusinessDetailsIn {
  name?: string | null;
  categories?: Record<string, unknown> | null;
  services?: string[] | null;
  hours?: Record<string, unknown> | null;
  special_hours?: Record<string, unknown>[] | null;
}

/** Every Google location with official + merchant values. */
export async function fetchBusinessDetails(): Promise<BusinessDetailsOut[]> {
  const data = await apiFetch("/api/v1/profile/business-details");
  return (Array.isArray(data) ? data : []) as BusinessDetailsOut[];
}

/** Save merchant overrides for one location (they win over Google). */
export async function saveBusinessDetails(
  listingId: string,
  payload: BusinessDetailsIn,
): Promise<BusinessDetailsOut> {
  return apiFetch(`/api/v1/profile/business-details/${encodeURIComponent(listingId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
