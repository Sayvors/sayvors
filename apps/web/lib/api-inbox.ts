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
  /** Canonical lead label for the conversation, when a lead exists. */
  lead_category?: string | null;
  /** The human owner. NULL = unassigned. */
  assigned_to?: string | null;
  assigned_at?: string | null;
  assignee_name?: string | null;  /** Who answers this conversation. "human" mutes the AI. */
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
  /** Escalation clock — why the AI stopped and when it takes over again. */
  priority?: "normal" | "important";
  ai_miss_count?: number;
  /** Canonical lead label, refreshed with the thread state. */
  lead_category?: string | null;
  /** Who owns the conversation. */
  assigned_to?: string | null;
  assigned_at?: string | null;
  assignee_name?: string | null;
  priority_since?: string | null;
  escalated_at?: string | null;
  escalation_reminder_at?: string | null;
  handover_sent_at?: string | null;
  /** priority_since + escalation_resume_hours; null unless escalated. */
  resume_at?: string | null;
  escalation_resume_hours?: number;
  /** Provider-side WhatsApp block mirrored on the thread. */
  blocked_at?: string | null;
  blocked_by?: string | null;
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
  /** The wamid this message quotes, when it is a contextual reply. */
  reply_to_message_id?: string | null;
  /** Locally removed from this inbox; the customer still has it. */
  deleted_at?: string | null;
  deleted?: boolean;
  /** Authenticated inbox route for a stored attachment. */
  media_url?: string | null;
  media_mime_type?: string | null;
  media_filename?: string | null;
  created_at: string;
}

export interface InboxSendResult {
  message: InboxMessage;
  /** False when WhatsApp rejected it; `error` says why. */
  sent: boolean;
  error: string | null;
}

export interface InboxThreadPage {
  threads: InboxThread[];
  total: number;
  next_cursor: string | null;
}

export async function fetchInboxThreads(
  search = "",
  includeArchived = false,
  options: {
    cursor?: string | null;
    category?: string | null;
    priority?: string | null;
    important?: boolean | null;
    limit?: number;
  } = {},
): Promise<InboxThreadPage> {
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  if (includeArchived) params.set("include_archived", "true");
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.category) params.set("category", options.category);
  if (options.priority) params.set("priority", options.priority);
  if (options.important !== null && options.important !== undefined) {
    params.set("important", String(options.important));
  }
  if (options.limit) params.set("limit", String(options.limit));
  const q = params.toString() ? `?${params.toString()}` : "";
  const data = await apiFetch(`/api/v1/inbox/threads${q}`);
  return {
    threads: (data?.threads ?? []) as InboxThread[],
    total: Number(data?.total ?? 0),
    next_cursor: (data?.next_cursor ?? null) as string | null,
  };
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

/** Clear the server-side unread badge for a conversation. */
export async function markInboxThreadRead(
  channelId: string,
  contactPhone: string | null,
): Promise<void> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}/read`,
    { method: "POST" },
  );
}
/** Initial window for a thread; older pages load on demand. */
export const INBOX_THREAD_PAGE_SIZE = 100;

export async function fetchThreadMessages(
  channelId: string,
  contactPhone: string | null,
  options: { before?: string | null; limit?: number } = {},
): Promise<{
  messages: InboxMessage[];
  thread: ThreadState | null;
  next_cursor: string | null;
}> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  const params = new URLSearchParams({
    limit: String(options.limit ?? INBOX_THREAD_PAGE_SIZE),
  });
  if (options.before) params.set("before", options.before);
  const data = await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}?${params.toString()}`,
  );
  return {
    messages: (data?.messages ?? []) as InboxMessage[],
    thread: (data?.thread ?? null) as ThreadState | null,
    next_cursor: (data?.next_cursor ?? null) as string | null,
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

/** Block or unblock this customer on the WhatsApp number. */
export async function setInboxThreadBlocked(
  channelId: string,
  contactPhone: string | null,
  blocked: boolean,
): Promise<ThreadState> {
  const key = contactPhone ?? UNKNOWN_THREAD_KEY;
  return (await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(key)}/block`,
    { method: blocked ? "POST" : "DELETE" },
  )) as ThreadState;
}

/** One eligible owner for a channel, as returned by the assignee picker. */
export interface Assignee {
  user_id: string;
  name: string;
  email: string;
  role_name: string;
  is_owner: boolean;
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

/** People who can own a conversation on this channel (owner first). */
export async function fetchAssignees(channelId: string): Promise<Assignee[]> {
  const data = (await apiFetch(
    `/api/v1/inbox/assignees?channel_id=${encodeURIComponent(channelId)}`,
  )) as { assignees?: Assignee[] };
  return data.assignees ?? [];
}

/** Set or clear the conversation owner. Null unassigns. */
export async function assignInboxThread(
  channelId: string,
  contactPhone: string,
  assignedTo: string | null,
): Promise<ThreadState> {
  return (await apiFetch(
    `/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(contactPhone)}/assignee`,
    {
      method: "PATCH",
      body: JSON.stringify({ assigned_to: assignedTo }),
    },
  )) as ThreadState;
}

/** Throws with the provider's reason so the thread can show it as failed. */
export async function sendInboxMessage(params: {
  channelId: string;
  contactPhone: string;
  contactName?: string | null;
  content: string;
  replyToMessageId?: string | null;
}): Promise<InboxSendResult> {
  return (await apiFetch("/api/v1/inbox/send", {
    method: "POST",
    body: JSON.stringify({
      channel_id: params.channelId,
      contact_phone: params.contactPhone,
      contact_name: params.contactName ?? null,
      content: params.content,
      reply_to_message_id: params.replyToMessageId ?? null,
    }),
  })) as InboxSendResult;
}

/** Send a native WhatsApp location card. */
export async function sendInboxLocation(params: {
  channelId: string;
  contactPhone: string;
  latitude: number;
  longitude: number;
  name?: string | null;
  address?: string | null;
}): Promise<InboxSendResult> {
  return (await apiFetch("/api/v1/inbox/send-location", {
    method: "POST",
    body: JSON.stringify({
      channel_id: params.channelId,
      contact_phone: params.contactPhone,
      latitude: params.latitude,
      longitude: params.longitude,
      name: params.name ?? null,
      address: params.address ?? null,
    }),
  })) as InboxSendResult;
}

/** Send a native WhatsApp contact card. */
export async function sendInboxContact(params: {
  channelId: string;
  contactPhone: string;
  name: string;
  phone: string;
  email?: string | null;
}): Promise<InboxSendResult> {
  return (await apiFetch("/api/v1/inbox/send-contact", {
    method: "POST",
    body: JSON.stringify({
      channel_id: params.channelId,
      contact_phone: params.contactPhone,
      name: params.name,
      phone: params.phone,
      email: params.email ?? null,
    }),
  })) as InboxSendResult;
}

/** Send a document (PDF, invoice, menu) as a native WhatsApp attachment. */
export async function sendInboxDocument(params: {
  channelId: string;
  contactPhone: string;
  file: File;
  caption?: string | null;
}): Promise<InboxSendResult> {
  const form = new FormData();
  form.append("channel_id", params.channelId);
  form.append("contact_phone", params.contactPhone);
  form.append("caption", params.caption ?? "");
  form.append("file", params.file);
  return (await apiFetch("/api/v1/inbox/send-document", {
    method: "POST",
    body: form,
  })) as InboxSendResult;
}

/** Send a WebP sticker. */
export async function sendInboxSticker(params: {
  channelId: string;
  contactPhone: string;
  file: File;
}): Promise<InboxSendResult> {
  const form = new FormData();
  form.append("channel_id", params.channelId);
  form.append("contact_phone", params.contactPhone);
  form.append("file", params.file);
  return (await apiFetch("/api/v1/inbox/send-sticker", {
    method: "POST",
    body: form,
  })) as InboxSendResult;
}

/** React to a message; an empty emoji removes this business's reaction. */
export async function reactToInboxMessage(
  messageId: string,
  emoji: string,
): Promise<InboxSendResult> {
  return (await apiFetch(
    `/api/v1/inbox/messages/${encodeURIComponent(messageId)}/reaction`,
    {
      method: "POST",
      body: JSON.stringify({ emoji }),
    },
  )) as InboxSendResult;
}

/** Remove one message from this inbox. Not a WhatsApp retraction. */
export async function removeInboxMessage(
  messageId: string,
): Promise<InboxMessage> {
  return (await apiFetch(
    `/api/v1/inbox/messages/${encodeURIComponent(messageId)}`,
    { method: "DELETE" },
  )) as InboxMessage;
}
