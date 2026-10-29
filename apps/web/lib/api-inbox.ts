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
  /** complaint | feedback | normal | … */
  category?: string | null;
  /** urgent | high | normal | low */
  priority?: string | null;
  /** Who answers this conversation. "human" mutes the AI. */
  mode?: "ai" | "human";
  mode_changed_at?: string | null;
  /** "system" for the automatic escalation, otherwise the acting user id. */
  mode_changed_by?: string | null;
  /** Needs a human now — urgent/high priority or a complaint. One rule
   * for every source, so a Google review and a WhatsApp thread mean the
   * same thing here. */
  important?: boolean;
  /** False for a conversation that cannot be answered from the inbox —
   * a Google review is answered through the review-reply flow. */
  can_reply?: boolean;
  /** Soft-archived: hidden from the default inbox view. */
  archived?: boolean;
  /** Soft-pinned: sorts to the top of the inbox list. */
  pinned?: boolean;
}

/** The newest stored summary of a conversation, shown as a card in the
 *  thread and injected into the AI prompt. */
export interface ThreadContext {
  summary: string;
  message_count: number;
  /** mode_change | resolve | escalation | periodic | manual */
  reason: string;
  created_at: string;
}

export interface ThreadState {
  mode: "ai" | "human";
  mode_changed_at: string | null;
  mode_changed_by: string | null;
  context: ThreadContext | null;
  /** Meta's 24h customer-service window. False = only a template can be sent. */
  reply_window_open?: boolean;
  /** Consent basis for templates. Null means none recorded. */
  opt_in_at?: string | null;
  opt_in_source?: string | null;
  opted_out?: boolean;
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

export async function fetchInboxThreads(search = "", includeArchived = false): Promise<InboxThread[]> {
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  if (includeArchived) params.set("include_archived", "true");
  const q = params.toString() ? `?${params.toString()}` : "";
  const data = await apiFetch(`/api/v1/inbox/threads${q}`);
  return (data?.threads ?? []) as InboxThread[];
}

export async function archiveInboxThread(channelId: string, contactPhone: string | null, archived: boolean): Promise<void> {
  const key = contactPhone ?? "unknown";
  await apiFetch(`/api/v1/inbox/threads/${channelId}/${encodeURIComponent(key)}/archive`, {
    method: "PATCH",
    body: JSON.stringify({ archived }),
  });
}

export async function pinInboxThread(channelId: string, contactPhone: string | null, pinned: boolean): Promise<void> {
  const key = contactPhone ?? "unknown";
  await apiFetch(`/api/v1/inbox/threads/${channelId}/${encodeURIComponent(key)}/pin`, {
    method: "PATCH",
    body: JSON.stringify({ pinned }),
  });
}

export async function deleteInboxThread(channelId: string, contactPhone: string | null): Promise<void> {
  const key = contactPhone ?? "unknown";
  await apiFetch(`/api/v1/inbox/threads/${channelId}/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
}
export async function fetchThreadMessages(
  channelId: string,
  contactPhone: string | null,
): Promise<{ messages: InboxMessage[]; thread: ThreadState | null }> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  const data = await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}`,
  );
  return {
    messages: (data?.messages ?? []) as InboxMessage[],
    thread: (data?.thread ?? null) as ThreadState | null,
  };
}

/** Switch the conversation between AI and human ownership. */
export async function setInboxThreadMode(
  channelId: string,
  contactPhone: string | null,
  mode: "ai" | "human",
): Promise<ThreadState> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  return (await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}/mode`,
    {
      method: "PATCH",
      body: JSON.stringify({ mode }),
    },
  )) as ThreadState;
}

/** Close the human session and hand the thread back to the AI. */
export async function resolveInboxThread(
  channelId: string,
  contactPhone: string | null,
): Promise<ThreadState> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  return (await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}/resolve`,
    { method: "POST" },
  )) as ThreadState;
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
