"use client";

import { apiFetch } from "./api-rag";

export type MetaProvider = "whatsapp" | "facebook" | "instagram";

export interface MetaConnection {
  id: string;
  provider: MetaProvider;
  connection_type: string;
  meta_business_id: string | null;
  scopes: string[];
  status: string;
  last_validated_at: string | null;
  last_successful_api_call_at: string | null;
  last_webhook_received_at: string | null;
  created_at: string;
}

export interface MetaAsset {
  id: string;
  provider: MetaProvider;
  asset_type: string;
  external_asset_id: string;
  parent_asset_id: string | null;
  name: string | null;
  username: string | null;
  phone: string | null;
  active: boolean;
  status: string;
}

export interface MetaConnectEntry {
  provider: string;
  auth_url?: string | null;
  fb_app_id?: string | null;
  /** Embedded Signup config for the standard (new number) flow. */
  fb_config_id?: string | null;
  /**
   * Embedded Signup config for the Coexistence flow ("Connect existing",
   * the customer keeps their number + WhatsApp Business App). Meta scopes
   * this to a separate Builder configuration, so the two flows cannot
   * share one config_id. Server falls back to fb_config_id when unset.
   */
  fb_coexistence_config_id?: string | null;
  graph_api_version?: string | null;
  solution_id?: string | null;
  state: string;
  note?: string | null;
}

export const fetchMetaConnections = (): Promise<{ connections: MetaConnection[] }> =>
  apiFetch("/api/v1/meta/connections");

export const startMetaConnect = (provider: MetaProvider): Promise<MetaConnectEntry> =>
  apiFetch(`/api/v1/meta/${provider}/connect`, { method: "POST" });

export const postWhatsAppSession = (body: {
  state: string;
  code?: string | null;
  waba_id?: string | null;
  phone_number_id?: string | null;
  business_id?: string | null;
  /** 6-digit two-step PIN. Without it Meta refuses to register the number. */
  pin?: string | null;
  /** Onboarding mode: 'standard' (new number) or 'coexistence' (existing Business app number) */
  mode?: "standard" | "coexistence" | null;
}): Promise<{
  connected: boolean;
  assets_found: number;
  registered?: string[];
  registration_failed?: { asset_id: string; asset_type: string; status: number }[];
  /** The number connected but cannot send until a PIN is supplied. */
  needs_pin?: boolean;
}> =>
  apiFetch("/api/v1/meta/whatsapp/session", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** Retry registration for a number Meta rejected (allowed for 14 days). */
export const registerWhatsAppNumber = (
  phoneNumberId: string,
  pin: string
): Promise<{ registered: boolean; phone_number_id: string }> =>
  apiFetch(`/api/v1/meta/whatsapp/${encodeURIComponent(phoneNumberId)}/register`, {
    method: "POST",
    body: JSON.stringify({ pin }),
  });

export const fetchMetaAssets = (
  provider: MetaProvider
): Promise<{ assets: MetaAsset[] }> => apiFetch(`/api/v1/meta/${provider}/assets`);

export const selectMetaAssets = (
  provider: MetaProvider,
  asset_ids: string[]
): Promise<{ assets: MetaAsset[] }> =>
  apiFetch(`/api/v1/meta/${provider}/assets/select`, {
    method: "POST",
    body: JSON.stringify({ asset_ids }),
  });

export const discoverInstagram = (): Promise<{ assets: MetaAsset[] }> =>
  apiFetch("/api/v1/meta/instagram/discover", { method: "POST" });

export const validateMeta = (provider: MetaProvider) =>
  apiFetch(`/api/v1/meta/${provider}/validate`, { method: "POST" });

/**
 * Instagram business profile — READ ONLY.
 *
 * Meta's IG User reference states updating a profile is not supported, so
 * there is deliberately no update call here. Everything on this page is
 * rendered as a value, never as an editable field.
 */
export interface InstagramProfile {
  username: string | null;
  name: string | null;
  biography: string | null;
  website: string | null;
  profile_picture_url: string | null;
  followers_count: number;
  follows_count: number;
  media_count: number;
  // Meta does not expose account_type on the IG User node, so Sayvors reports
  // what it stores at connect time instead.
  status: string | null;
  eligibility: string | null;
  parent_page_id: string | null;
  parent_page_name: string | null;
  synced_at: string | null;
  stale: boolean;
}

export const fetchInstagramProfile = (
  igId: string
): Promise<InstagramProfile> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/profile`);

export const disconnectMeta = (provider: MetaProvider, opts?: { deleteData?: boolean }) =>
  apiFetch(
    `/api/v1/meta/${provider}/disconnect${opts?.deleteData ? "?delete_data=true" : ""}`,
    { method: "DELETE" },
  );
