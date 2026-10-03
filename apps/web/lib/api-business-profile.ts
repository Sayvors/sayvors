"use client";

import { apiFetch } from "./api-rag";

export interface BusinessProfileData {
  id: string;
  summary?: string | null;
  domain?: string | null;
  products_services?: string | null;
  not_offered_and_policies?: string | null;
  audience_languages?: string | null;
  source?: "auto" | "edited";
  generated_at?: string | null;
  updated_at?: string | null;
}

export async function getBusinessProfile(): Promise<BusinessProfileData | null> {
  const data = await apiFetch("/api/v1/profile/business");
  return data?.profile ?? null;
}

export async function saveBusinessProfile(
  fields: Partial<Omit<BusinessProfileData, "id" | "source" | "generated_at" | "updated_at">>
): Promise<BusinessProfileData> {
  const data = await apiFetch("/api/v1/profile/business", {
    method: "PUT",
    body: JSON.stringify(fields),
  });
  return data.profile;
}

/** Regenerates from the databank. Edited fields always survive — only empty ones get filled. */
export async function regenerateBusinessProfile(): Promise<BusinessProfileData> {
  const data = await apiFetch("/api/v1/profile/business/regenerate", {
    method: "POST",
  });
  return data.profile;
}
