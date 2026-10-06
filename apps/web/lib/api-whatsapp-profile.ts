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
  synced_at: string | null;
  stale: boolean;
};

export type WaUsage = {
  used_this_month: number;
  monthly_limit: number;
  plan: string;
};

export async function fetchWaProfile(phoneId: string): Promise<WaProfile> {
  return apiFetch(`/api/v1/meta/whatsapp/${encodeURIComponent(phoneId)}/profile`);
}

export async function fetchWhatsAppUsage(): Promise<WaUsage> {
  return apiFetch("/api/v1/meta/whatsapp/usage");
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

/** 0-100: about 40 + description 30 + websites 20 + contact 10.
 * Photo is deliberately not scored — there is no upload API to manage it,
 * and the score should only reflect what the business can actually edit. */
export function completeness(p: WaProfile | null): number {
  if (!p) return 0;
  let s = 0;
  if ((p.about ?? "").trim()) s += 40;
  if ((p.description ?? "").trim()) s += 30;
  if ((p.websites ?? []).length > 0) s += 20;
  if ((p.address ?? "").trim() || (p.email ?? "").trim()) s += 10;
  return Math.min(100, s);
}

/** "just now" / "5m ago" / "3h ago" / "12d ago" for synced-at labels. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export const WA_VERTICALS = [
  "Restaurant", "Retail", "Services", "Health", "Education", "Automotive",
  "Beauty", "Real Estate", "Travel", "Other",
];
