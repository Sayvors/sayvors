"use client";

import { apiFetch } from "./api-rag";

export interface ChannelRow {
  id: string;
  platform: string;
  platform_user_id: string | null;
  display_name: string | null;
  status: string;
}

export interface AutoReplyConfig {
  enabled: boolean;
  approval_mode?: string;
}

/** All channels the tenant owns (inbox rows, google locations, whatsapp numbers). */
export async function fetchChannels(): Promise<ChannelRow[]> {
  const data = await apiFetch("/api/v1/channels?limit=100");
  return (data.channels ?? []) as ChannelRow[];
}

/** The whatsapp Channel row for a phone_number_id — created transparently
 * when missing, because Channel rows only start existing once the first
 * inbound webhook arrived (the consumer creates them). Settings that target
 * the channel (auto-reply) need the row to exist NOW. */
export async function ensureWhatsAppChannel(
  phoneId: string,
  displayName?: string | null
): Promise<ChannelRow> {
  const channels = await fetchChannels();
  const found = channels.find(
    (c) => c.platform === "whatsapp" && c.platform_user_id === phoneId
  );
  if (found) return found;
  try {
    return (await apiFetch("/api/v1/channels/", {
      method: "POST",
      body: JSON.stringify({
        platform: "whatsapp",
        platform_user_id: phoneId,
        display_name: displayName || "WhatsApp",
      }),
    })) as ChannelRow;
  } catch (e) {
    // 409 = created concurrently (first message landed meanwhile) — re-read.
    if (e instanceof Error && e.message.includes("409")) {
      const fresh = await fetchChannels();
      const row = fresh.find(
        (c) => c.platform === "whatsapp" && c.platform_user_id === phoneId
      );
      if (row) return row;
    }
    throw e;
  }
}

export async function getAutoReply(channelId: string): Promise<AutoReplyConfig> {
  return apiFetch(`/api/v1/channels/${channelId}/autoreply`);
}

export async function updateAutoReply(
  channelId: string,
  patch: Partial<AutoReplyConfig>
): Promise<AutoReplyConfig> {
  return apiFetch(`/api/v1/channels/${channelId}/autoreply`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}
