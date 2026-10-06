"use client";

import { apiFetch } from "./api-rag";

export type WaProfile = {
  about: string | null;
  address: string | null;
  description: string | null;
  email: string | null;
  websites: string[];
  vertical: string | null;
  profile_picture_url: string | null;
};

export async function fetchWaProfile(phoneId: string): Promise<WaProfile> {
  return apiFetch(`/api/v1/meta/whatsapp/${encodeURIComponent(phoneId)}/profile`);
}

export async function saveWaProfile(phoneId: string, patch: Partial<WaProfile>): Promise<WaProfile> {
  return apiFetch(`/api/v1/meta/whatsapp/${encodeURIComponent(phoneId)}/profile`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function normalizeUrl(u: string): string {
  const t = u.trim();
  if (!t) return t;
  return /^https?:\/\//i.test(t) ? t : `https://${t}`;
}

/** 0-100: photo 30 + about 25 + description 20 + websites 15 + contact 10 */
export function completeness(p: WaProfile | null): number {
  if (!p) return 0;
  let s = 0;
  if (p.profile_picture_url) s += 30;
  if ((p.about ?? "").trim()) s += 25;
  if ((p.description ?? "").trim()) s += 20;
  if ((p.websites ?? []).length > 0) s += 15;
  if ((p.address ?? "").trim() || (p.email ?? "").trim()) s += 10;
  return Math.min(100, s);
}

export const WA_VERTICALS = [
  "Restaurant", "Retail", "Services", "Health", "Education", "Automotive",
  "Beauty", "Real Estate", "Travel", "Other",
];
