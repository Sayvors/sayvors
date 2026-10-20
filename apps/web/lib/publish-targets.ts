"use client";

import { apiFetch } from "./api-rag";
import { fetchMetaAssets } from "./api-meta";
import type { PublishTarget } from "@/components/dashboard/publish/types";

/*
 * One loader for every publish destination the composer and the published-
 * posts list need. Kept out of the components so both show identical names
 * (Meta assets + Google Business Profile locations), fetched exactly once
 * per mount instead of each half re-deriving its own list.
 */

export interface PublishTargetSet {
  social: PublishTarget[];
  google: PublishTarget[];
}

interface RawMetaAsset {
  asset_type: string;
  active: boolean;
  external_asset_id: string;
  name: string | null;
  username: string | null;
  phone: string | null;
}

const META_PROVIDERS = ["facebook", "instagram", "whatsapp"] as const;

export async function fetchPublishTargets(): Promise<PublishTargetSet> {
  const results = await Promise.allSettled([
    ...META_PROVIDERS.map((p) => fetchMetaAssets(p)),
    apiFetch("/api/v1/channels?limit=100"),
  ]);
  const social: PublishTarget[] = [];
  const google: PublishTarget[] = [];

  // Meta assets: WhatsApp numbers and Facebook/Instagram pages or accounts.
  META_PROVIDERS.forEach((provider, i) => {
    const r = results[i];
    const assets = (r.status === "fulfilled" ? r.value.assets ?? [] : []) as RawMetaAsset[];
    const active = assets.filter((a) => a.active);
    if (provider === "whatsapp") {
      active
        .filter((a) => a.asset_type === "phone_number")
        .forEach((a) =>
          social.push({
            id: `wa:${a.external_asset_id}`,
            platform: "whatsapp",
            name: a.phone ?? a.name ?? "WhatsApp number",
            handle: a.phone ?? null,
          }),
        );
    } else {
      active
        .filter((a) => a.asset_type === "page" || a.asset_type === "account")
        .forEach((a) =>
          social.push({
            id: `${provider}:${a.external_asset_id}`,
            platform: provider,
            name: a.name ?? a.username ?? a.external_asset_id,
            handle: a.username ?? null,
          }),
        );
    }
  });

  // Google Business Profile locations come from the channels table.
  const channelsResult = results[META_PROVIDERS.length];
  if (channelsResult.status === "fulfilled") {
    const channels =
      (channelsResult.value as {
        channels?: Array<{
          id: string;
          platform: string;
          display_name: string | null;
          listing_id: string | null;
          status: string;
        }>;
      }).channels ?? [];
    channels
      .filter((c) => c.platform === "google_reviews" && c.status === "active")
      .forEach((c) => {
        google.push({
          id: `google:${c.id}`,
          platform: "google_reviews",
          name: c.display_name ?? "Google Business Profile",
          handle: c.listing_id ?? null,
          locationId: c.listing_id ?? null,
        });
      });
  }

  return { social, google };
}

/** The publish API's `external_asset_id` for a target: the raw Meta asset id,
 * or the Google location (listing) id. Returns null when a Google row is
 * missing its location id and therefore cannot be published to. */
export function externalAssetIdFor(t: PublishTarget): string | null {
  if (t.platform === "google_reviews") return t.locationId || null;
  const idx = t.id.indexOf(":");
  return idx === -1 ? t.id : t.id.slice(idx + 1);
}
