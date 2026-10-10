/* Inbox API — per-customer WhatsApp threads.
 *
 * A channel is a phone number serving many customers, so the inbox is threaded
 * by (channel, contact) rather than reading channel_messages flat. The backend
 * groups in SQL; the "unknown" key is the catch-all for rows written before
 * contact_phone existed.
 */
import { apiFetch } from "@/lib/api-rag";

export const UNKNOWN_THREAD_KEY = "unknown";

export interface InboxThread {
  key: string;
  contact_phone: string | null;
  display_name: string | null;
  username: string | null;
  avatar_url: string | null;
  channel_id: string;
  channel_name: string | null;
  platform: string | null;
  last_message: string;
  last_message_at: string;
  last_direction: string;
  message_count: number;
  unread: number;
  is_unknown: boolean;
}

export interface InboxMessage {
  id: string;
  channel_id: string;
  platform_message_id: string | null;
  direction: "inbound" | "outbound";
  content: string;
  content_type: string;
  status: "sent" | "delivered" | "read" | "failed";
  error: string | null;
  contact_phone: string | null;
  contact_name: string | null;
  created_at: string;
}

export interface InboxSendResult {
  message: InboxMessage;
  /** False when WhatsApp rejected it; `error` says why. */
  sent: boolean;
  error: string | null;
}

export async function fetchInboxThreads(search = ""): Promise<InboxThread[]> {
  const q = search.trim() ? `?search=${encodeURIComponent(search.trim())}` : "";
  const data = await apiFetch(`/api/v1/inbox/threads${q}`);
  return (data?.threads ?? []) as InboxThread[];
}

export async function fetchThreadMessages(
  channelId: string,
  contactPhone: string | null,
): Promise<InboxMessage[]> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  const data = await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}`,
  );
  return (data?.messages ?? []) as InboxMessage[];
}

/** Throws with the provider's reason so the thread can show it as failed. */
export async function sendInboxMessage(params: {
  channelId: string;
  contactPhone: string;
  contactName?: string | null;
  content: string;
}): Promise<InboxSendResult> {
  return (await apiFetch("/api/v1/inbox/send", {
    method: "POST",
    body: JSON.stringify({
      channel_id: params.channelId,
      contact_phone: params.contactPhone,
      contact_name: params.contactName ?? null,
      content: params.content,
    }),
  })) as InboxSendResult;
}
