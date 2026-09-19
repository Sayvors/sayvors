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
  fb_config_id?: string | null;
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
}): Promise<{ connected: boolean; assets_found: number }> =>
  apiFetch("/api/v1/meta/whatsapp/session", {
    method: "POST",
    body: JSON.stringify(body),
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

export const disconnectMeta = (provider: MetaProvider) =>
  apiFetch(`/api/v1/meta/${provider}/disconnect`, { method: "DELETE" });
