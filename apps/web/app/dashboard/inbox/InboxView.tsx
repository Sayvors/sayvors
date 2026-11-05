"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import LogoLoader from "@/components/LogoLoader";
import {
  fetchInboxThreads,
  fetchThreadMessages,
  archiveInboxThread,
  assignInboxThread,
  deleteInboxThread,
  fetchAssignees,
  pinInboxThread,
  resolveInboxThread,
  sendInboxMessage,
  sendInboxLocation,
  sendInboxContact,
  sendInboxDocument,
  sendInboxSticker,
  setInboxThreadMode,
  setInboxThreadBlocked,
  reactToInboxMessage,
  removeInboxMessage,
  UNKNOWN_THREAD_KEY,
  type InboxMessage,
  type InboxThread,
  type ThreadState,
} from "@/lib/api-inbox";
import { apiFetch } from "@/lib/api-rag";
import { useAuth } from "@/lib/auth-context";
import { platformMeta } from "@/lib/platform";
import { resolveMediaUrl } from "@/lib/media-url";
import { setActiveThread } from "@/lib/active-thread";
import {
  clearThreadTyping,
  setAiTyping,
  setCustomerAwaiting,
  useTypingSource,
} from "@/lib/inbox-typing";
import { leadCategoryLabel } from "@/lib/lead-labels";
import { useInboxRealtime, type InboxRealtimeEvent } from "@/lib/use-inbox-realtime";
import { useVirtualizer } from "@tanstack/react-virtual";
import TypingIndicator from "@/components/inbox/TypingIndicator";
import {
  listWhatsAppTemplates,
  recordWhatsAppConsent,
  sendWhatsAppTemplate,
  type WhatsAppTemplate,
} from "@/lib/api-whatsapp-templates";

type Filter = "all" | "unread" | "important" | "mine" | "unknown";

const QUICK_REPLIES = [
  "Thanks for reaching out! How can I help?",
  "Sure, give me a moment to check that.",
  "Could you share more details?",
  "All set — anything else I can do for you?",
];

const REACTION_EMOJIS = ["👍", "❤️", "😂", "🙏", "🎉", "👀"];

/** Cap on the in-memory thread message buffer. Older entries are dropped on
 *  overflow; the server stays the source of truth and the thread is
 *  re-fetched on reopen. Keeps a long-lived inbox session (or a realtime
 *  flood) from growing the array without bound. */
const INBOX_MESSAGE_BUFFER_CAP = 500;

/** "+966500000001" / "966500000001" -> "+966 50 000 0001" for scannability. */
function formatPhone(phone: string | null): string {
  if (!phone) return "Unknown sender";
  const p = phone.startsWith("+") ? phone : `+${phone}`;
  if (p.length <= 8) return p;
  const head = p.slice(0, 4);
  const rest = p.slice(4);
  return head + " " + rest.replace(/(\d{1,3})(?=(\d{3})+$)/g, "$1 ").trim();
}

function initials(name: string | null, phone: string | null): string {
  const base = (name || phone || "?").trim();
  const parts = base.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return base.slice(0, 2).toUpperCase();
}

/**
 * Why a conversation is flagged important — shown on the badge's tooltip.
 * The rule is the same for every source, so the reason is the
 * conversation's own category and priority, never its platform.
 */
function importantReason(t: {
  category?: string | null;
  priority?: string | null;
}): string {
  const p = (t.priority || "normal").toLowerCase();
  const c = (t.category || "normal").toLowerCase();
  if (p === "urgent") return "Marked urgent — needs an answer now.";
  if (c === "complaint") return "A complaint — needs an answer now.";
  if (p === "high") return "Marked high priority.";
  return "Needs a human now.";
}

/** Profile picture when the platform gave us one, initials otherwise. */
function Avatar({
  name,
  phone,
  url,
  boxCls,
  children,
}: {
  name: string | null;
  phone: string | null;
  url: string | null | undefined;
  boxCls: string;
  children?: ReactNode;
}) {
  // Meta avatar urls are signed CDN links that expire — when one fails to
  // load, fall back to initials instead of a broken-image icon. Tracking
  // the failed url (not a boolean) means a refreshed url recovers on its
  // own without an effect.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const show = url != null && failedUrl !== url;
  return (
    <span className="relative shrink-0" aria-hidden>
      {show ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={url}
          src={url}
          alt=""
          onError={() => setFailedUrl(url)}
          className={`object-cover ${boxCls}`}
        />
      ) : (
        <span className={`flex items-center justify-center font-bold ${boxCls}`}>
          {initials(name, phone)}
        </span>
      )}
      {children}
    </span>
  );
}

function relative(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(iso).toLocaleDateString("en", { month: "short", day: "numeric" });
}

/** Time until an ISO instant, for the auto-resume countdown. Unlike
 *  `relative` this counts forward, and "due now" is meaningful: the sweep may
 *  simply not have run yet, so it must not read as if the AI already resumed. */
function remaining(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.round((then - Date.now()) / 60000);
  if (mins <= 0) return "due now";
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  if (hours < 24) return `in ${hours}h${rest ? ` ${rest}m` : ""}`;
  const days = Math.floor(hours / 24);
  const rem = hours % 24;
  return `in ${days}d${rem ? ` ${rem}h` : ""}`;
}

/** Elapsed time for the escalation chip. `relative` returns a bare magnitude
 *  used elsewhere ("12m"), which would read "now ago" here. */
function ago(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Reminder state for an escalated thread. A NULL reminder next to a sent
 *  escalation means the reminder already fired — the sweep nulls it — not that
 *  none was ever armed. */
function reminderLabel(state: ThreadState): string {
  if (!state.escalated_at) return "Escalation email not delivered";
  const at = state.escalation_reminder_at;
  if (!at) return "Reminder already sent";
  return remaining(at) === "due now" ? "Reminder due" : `Reminder ${remaining(at)}`;
}

/** Extract lat/lng from the common Google Maps link shapes. */
function coordsFromMapsLink(link: string): { lat: number; lng: number } | null {
  const patterns = [
    /@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
    /[?&]q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
    /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,
  ];
  for (const pattern of patterns) {
    const match = link.match(pattern);
    if (!match) continue;
    const lat = Number(match[1]);
    const lng = Number(match[2]);
    if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng };
  }
  return null;
}

function clockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit" });
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return "Today";
  const yesterday = new Date(today.getTime() - 86400000);
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString("en", { month: "short", day: "numeric" });
}

/** Why a context snapshot was written, in the reader's language. */
function contextReasonLabel(reason: string): string {
  switch (reason) {
    case "mode_change":
      return "when the mode changed";
    case "resolve":
      return "when the thread was resolved";
    case "escalation":
      return "when it was escalated";
    case "periodic":
      return "mid-conversation";
    case "cross_channel":
      return "when they moved from Instagram";
    default:
      return "manually";
  }
}

function PlatformBadge({ platform }: { platform: string | null }) {
  const meta = platformMeta(platform);
  if (!meta.icon) return null;
  return (
    <span className="absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-white dark:bg-ink">
      <Image src={meta.icon} alt={meta.label} width={14} height={14} className="rounded-full" />
    </span>
  );
}

function StatusTick({ message }: { message: InboxMessage }) {
  if (message.status === "failed") {
    return <span className="font-bold text-red-400">!</span>;
  }
  const color = message.status === "read" ? "text-sky-300" : "text-white/70";
  const double = message.status === "delivered" || message.status === "read";
  return (
    <span className={color}>
      {double ? "✓✓" : "✓"}
    </span>
  );
}

const REPLY_WINDOW_MS = 24 * 60 * 60 * 1000;

/** Meta's free-form messaging window: 24h from the customer's last inbound
 *  message. Returns the expiry timestamp, or null for platforms without a
 *  hard window (e.g. Google reviews, which are answered elsewhere). */
function replyWindowExpiresAt(thread: InboxThread | null): Date | null {
  if (!thread) return null;
  const platform = (thread.platform ?? "").toLowerCase();
  if (platform === "google_reviews" || platform === "google") return null;
  if (!thread.last_message_at) return null;
  // If the last message was outbound, the customer's last inbound was
  // earlier — use last_message_at as a conservative (slightly generous)
  // reference so we never block a reply that might still be allowed.
  return new Date(new Date(thread.last_message_at).getTime() + REPLY_WINDOW_MS);
}

function replyWindowOpen(thread: InboxThread | null): boolean {
  const expires = replyWindowExpiresAt(thread);
  if (!expires) return true; // no window constraint
  return Date.now() < expires.getTime();
}

export default function InboxView() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [nextThreadCursor, setNextThreadCursor] = useState<string | null>(null);
  const [loadingMoreThreads, setLoadingMoreThreads] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<InboxThread | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [listActionError, setListActionError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  // Older-page cursor and its loading/limit state. The initial window is
  // capped (api-inbox INBOX_THREAD_PAGE_SIZE); older messages are fetched only
  // when the agent asks for them.
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [earlierError, setEarlierError] = useState<string | null>(null);
  const [historyLimitReached, setHistoryLimitReached] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Prepending older messages must keep the viewport anchored. The layout
  // effect restores the old scroll offset; the passive auto-scroll effect
  // skips exactly one run so it cannot jump to the bottom.
  const prependScrollRef = useRef<{ height: number; top: number } | null>(null);
  const skipAutoScrollRef = useRef(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [threadQuery, setThreadQuery] = useState("");
  const [showInfo, setShowInfo] = useState(false);
  const [photoOpen, setPhotoOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [threadState, setThreadState] = useState<ThreadState | null>(null);
  const [modeBusy, setModeBusy] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [blockBusy, setBlockBusy] = useState(false);
  const [blockError, setBlockError] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<InboxMessage | null>(null);
  const [reactingTo, setReactingTo] = useState<string | null>(null);
  const [reactBusy, setReactBusy] = useState(false);
  const [richComposer, setRichComposer] = useState<
    "location" | "contact" | "document" | "sticker" | null
  >(null);
  const [richBusy, setRichBusy] = useState(false);
  const [locName, setLocName] = useState("");
  const [locAddress, setLocAddress] = useState("");
  const [locLat, setLocLat] = useState("");
  const [locLng, setLocLng] = useState("");
  const [locMaps, setLocMaps] = useState("");
  const [cardName, setCardName] = useState("");
  const [cardPhone, setCardPhone] = useState("");
  const [cardEmail, setCardEmail] = useState("");
  const [docFile, setDocFile] = useState<File | null>(null);
  const [docCaption, setDocCaption] = useState("");
  const [stickerFile, setStickerFile] = useState<File | null>(null);
  const [assigneeBusy, setAssigneeBusy] = useState(false);
  const [assigneeError, setAssigneeError] = useState<string | null>(null);
  // The escalation clock is live: while an escalated thread is open, tick
  // every 30s so "AI resumes in 23h 48m" does not freeze at whatever it said
  // when the thread was opened.
  const [, setEscalationTick] = useState(0);
  useEffect(() => {
    if (threadState?.priority !== "important") return;
    const id = window.setInterval(
      () => setEscalationTick((n) => n + 1),
      30_000,
    );
    return () => window.clearInterval(id);
  }, [threadState?.priority]);
  // Templates: the only legal send once Meta's 24h window has closed.
  const [templates, setTemplates] = useState<WhatsAppTemplate[] | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateId, setTemplateId] = useState<string>("");
  const [templateVars, setTemplateVars] = useState<string[]>([]);
  const [templateBusy, setTemplateBusy] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const templateKeyRef = useRef<string>("");

  // Deep link (?channel=…&key=…) — the Instagram hub's Messages tab links
  // straight into a conversation. Captured once, applied on the first
  // threads load that contains the thread, then cleared so manual
  // navigation afterwards wins.
  const searchParams = useSearchParams();
  const deepLinkRef = useRef<{ channel: string | null; key: string | null }>({
    channel: null,
    key: null,
  });
  useEffect(() => {
    const ch = searchParams.get("channel");
    const key = searchParams.get("key");
    if (ch && key) deepLinkRef.current = { channel: ch, key };
  }, [searchParams]);

  const togglePin = async (thread: InboxThread) => {
    const composite = `${thread.channel_id}:${thread.key}`;
    const next = !thread.pinned;
    setListActionError(null);
    try {
      await pinInboxThread(thread.channel_id, thread.contact_phone, next);
      setThreads((prev) =>
        prev.map((t) =>
          `${t.channel_id}:${t.key}` === composite ? { ...t, pinned: next } : t,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
    } catch {
      setListActionError(
        next
          ? "Could not pin the conversation. Try again."
          : "Could not unpin the conversation. Try again.",
      );
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
    }
  };

  const handleArchive = async (thread: InboxThread, archived: boolean) => {
    const composite = `${thread.channel_id}:${thread.key}`;
    setListActionError(null);
    try {
      await archiveInboxThread(thread.channel_id, thread.contact_phone, archived);
      // Optimistic local update + cache invalidation.
      setThreads((prev) =>
        prev.map((t) =>
          `${t.channel_id}:${t.key}` === composite ? { ...t, archived } : t,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
    } catch {
      setListActionError(
        archived
          ? "Could not archive the conversation. Try again."
          : "Could not restore the conversation. Try again.",
      );
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
    }
  };

  const handleDelete = async (thread: InboxThread) => {
    if (deleteBusy) return;
    const composite = `${thread.channel_id}:${thread.key}`;
    setDeleteBusy(true);
    setListActionError(null);
    try {
      await deleteInboxThread(thread.channel_id, thread.contact_phone);
      setThreads((prev) => prev.filter((t) => `${t.channel_id}:${t.key}` !== composite));
      if (selectedKey === composite) setSelectedKey(null);
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
      setDeleteTarget(null);
    } catch {
      setListActionError("Could not delete the conversation. Try again.");
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
    } finally {
      setDeleteBusy(false);
    }
  };

  /** Apply a server-returned thread state to the open thread and its row. */
  const applyThreadState = (thread: InboxThread, state: ThreadState) => {
    setThreadState(state);
    setThreads((prev) =>
      prev.map((t) =>
        `${t.channel_id}:${t.key}` === `${thread.channel_id}:${thread.key}`
          ? {
              ...t,
              mode: state.mode,
              mode_changed_at: state.mode_changed_at,
              mode_changed_by: state.mode_changed_by,
              assigned_to: state.assigned_to ?? null,
              assigned_at: state.assigned_at ?? null,
              assignee_name: state.assignee_name ?? null,
            }
          : t,
      ),
    );
  };

  const react = async (message: InboxMessage, emoji: string) => {
    if (reactBusy) return;
    setReactBusy(true);
    setSendError(null);
    try {
      const result = await reactToInboxMessage(message.id, emoji);
      setMessages((prev) =>
        prev.some((m) => m.id === result.message.id)
          ? prev
          : [...prev, result.message],
      );
      setReactingTo(null);
      if (!result.sent) {
        setSendError(result.error || "WhatsApp rejected the reaction.");
      }
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the reaction.");
    } finally {
      setReactBusy(false);
    }
  };

  const removeMessage = async (message: InboxMessage) => {
    if (
      !window.confirm(
        "Remove this message from the inbox? The customer will still see it on their phone.",
      )
    ) {
      return;
    }
    setSendError(null);
    try {
      const updated = await removeInboxMessage(message.id);
      setMessages((prev) =>
        prev.map((m) => (m.id === updated.id ? updated : m)),
      );
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not remove the message.");
    }
  };

  const openRichComposer = (
    kind: "location" | "contact" | "document" | "sticker",
  ) => {
    setRichComposer(kind);
    setSendError(null);
    if (kind === "location") {
      setLocName("");
      setLocAddress("");
      setLocLat("");
      setLocLng("");
      setLocMaps("");
    } else if (kind === "contact") {
      setCardName("");
      setCardPhone("");
      setCardEmail("");
    } else if (kind === "document") {
      setDocFile(null);
      setDocCaption("");
    } else {
      setStickerFile(null);
    }
  };

  const appendRichMessage = (message: InboxMessage) => {
    setMessages((prev) =>
      prev.some((m) => m.id === message.id) ? prev : [...prev, message],
    );
    void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
  };

  const sendLocationCard = async () => {
    const thread = target;
    if (!thread?.contact_phone || richBusy) return;
    const lat = Number(locLat);
    const lng = Number(locLng);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
      setSendError("Enter a latitude between -90 and 90.");
      return;
    }
    if (!Number.isFinite(lng) || lng < -180 || lng > 180) {
      setSendError("Enter a longitude between -180 and 180.");
      return;
    }
    setRichBusy(true);
    setSendError(null);
    try {
      const result = await sendInboxLocation({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone,
        latitude: lat,
        longitude: lng,
        name: locName.trim() || null,
        address: locAddress.trim() || null,
      });
      if (!result.sent) {
        setSendError(result.error || "WhatsApp rejected the location.");
        return;
      }
      appendRichMessage(result.message);
      setRichComposer(null);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the location.");
    } finally {
      setRichBusy(false);
    }
  };

  const sendContactCard = async () => {
    const thread = target;
    if (!thread?.contact_phone || richBusy) return;
    if (!cardName.trim() || !cardPhone.trim()) {
      setSendError("A contact card needs a name and a phone number.");
      return;
    }
    setRichBusy(true);
    setSendError(null);
    try {
      const result = await sendInboxContact({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone,
        name: cardName.trim(),
        phone: cardPhone.trim(),
        email: cardEmail.trim() || null,
      });
      if (!result.sent) {
        setSendError(result.error || "WhatsApp rejected the contact card.");
        return;
      }
      appendRichMessage(result.message);
      setRichComposer(null);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the contact card.");
    } finally {
      setRichBusy(false);
    }
  };

  const sendDocumentFile = async () => {
    const thread = target;
    if (!thread?.contact_phone || richBusy) return;
    if (!docFile) {
      setSendError("Choose a document to send.");
      return;
    }
    setRichBusy(true);
    setSendError(null);
    try {
      const result = await sendInboxDocument({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone,
        file: docFile,
        caption: docCaption.trim() || null,
      });
      if (!result.sent) {
        setSendError(result.error || "WhatsApp rejected the document.");
        return;
      }
      appendRichMessage(result.message);
      setRichComposer(null);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the document.");
    } finally {
      setRichBusy(false);
    }
  };

  const sendStickerFile = async () => {
    const thread = target;
    if (!thread?.contact_phone || richBusy) return;
    if (!stickerFile) {
      setSendError("Choose a WebP sticker to send.");
      return;
    }
    setRichBusy(true);
    setSendError(null);
    try {
      const result = await sendInboxSticker({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone,
        file: stickerFile,
      });
      if (!result.sent) {
        setSendError(result.error || "WhatsApp rejected the sticker.");
        return;
      }
      appendRichMessage(result.message);
      setRichComposer(null);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the sticker.");
    } finally {
      setRichBusy(false);
    }
  };

  const handleModeChange = async (thread: InboxThread, next: "ai" | "human") => {
    if (modeBusy) return;
    setModeBusy(true);
    setModeError(null);
    try {
      const state = await setInboxThreadMode(
        thread.channel_id,
        thread.contact_phone,
        next,
      );
      applyThreadState(thread, state);
    } catch (e) {
      setModeError(
        e instanceof Error ? e.message : "Could not switch this conversation.",
      );
    } finally {
      setModeBusy(false);
    }
  };

  const handleAssignee = async (
    thread: InboxThread,
    assignedTo: string | null,
  ) => {
    if (assigneeBusy || !thread.contact_phone) return;
    setAssigneeBusy(true);
    setAssigneeError(null);
    try {
      const state = await assignInboxThread(
        thread.channel_id,
        thread.contact_phone,
        assignedTo,
      );
      applyThreadState(thread, state);
      void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] });
    } catch (e) {
      setAssigneeError(
        e instanceof Error ? e.message : "Could not assign this conversation.",
      );
    } finally {
      setAssigneeBusy(false);
    }
  };

  const handleResolve = async (thread: InboxThread) => {    if (modeBusy) return;
    setModeBusy(true);
    setModeError(null);
    try {
      const state = await resolveInboxThread(thread.channel_id, thread.contact_phone);
      applyThreadState(thread, state);
    } catch (e) {
      setModeError(
        e instanceof Error ? e.message : "Could not resolve this conversation.",
      );
    } finally {
      setModeBusy(false);
    }
  };

  const reloadThread = async (thread: InboxThread) => {
    const data = await fetchThreadMessages(thread.channel_id, thread.contact_phone);
    setMessages(data.messages);
    setNextCursor(data.next_cursor);
    setHistoryLimitReached(false);
    setEarlierError(null);
    if (data.thread) setThreadState(data.thread);
  };

  const handleBlockToggle = async (thread: InboxThread, blocked: boolean) => {
    if (blockBusy) return;
    setBlockBusy(true);
    setBlockError(null);
    try {
      const state = await setInboxThreadBlocked(
        thread.channel_id,
        thread.contact_phone,
        blocked,
      );
      applyThreadState(thread, state);
    } catch (e) {
      setBlockError(
        e instanceof Error
          ? e.message
          : blocked
            ? "Could not block this customer."
            : "Could not unblock this customer.",
      );
    } finally {
      setBlockBusy(false);
    }
  };

  const openTemplatePicker = async (thread: InboxThread) => {
    setTemplateError(null);
    setTemplateOpen(true);
    if (!templateKeyRef.current) {
      templateKeyRef.current =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${thread.channel_id}:${thread.key}:${Date.now()}`;
    }
    if (templates !== null) return;
    try {
      setTemplates((await listWhatsAppTemplates()).templates);
    } catch (e) {
      setTemplateError(
        e instanceof Error ? e.message : "Could not load templates.",
      );
    }
  };

  const chooseTemplate = (template: WhatsAppTemplate) => {
    setTemplateId(template.id);
    setTemplateVars(Array.from({ length: template.variables }, () => ""));
    setTemplateError(null);
  };

  const handleSendTemplate = async (thread: InboxThread) => {
    if (!selectedTemplate || templateBusy) return;
    if (
      selectedTemplate.variables > 0 &&
      templateVars.some((v) => !v.trim())
    ) {
      setTemplateError("Fill every variable before sending.");
      return;
    }
    setTemplateBusy(true);
    setTemplateError(null);
    try {
      const result = await sendWhatsAppTemplate({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone ?? "",
        templateId: selectedTemplate.id,
        variables: templateVars,
        // One key per picker session: a double click retries the same send
        // instead of billing two messages.
        idempotencyKey: templateKeyRef.current,
      });
      if (result.status === "sent") {
        setTemplateOpen(false);
        setTemplateId("");
        setTemplateVars([]);
        setTemplates(null);
        templateKeyRef.current = "";
        await reloadThread(thread);
      } else {
        setTemplateError(result.error ?? "Meta rejected the template.");
      }
    } catch (e) {
      setTemplateError(
        e instanceof Error ? e.message : "Could not send the template.",
      );
    } finally {
      setTemplateBusy(false);
    }
  };

  const handleRecordConsent = async (thread: InboxThread) => {
    setTemplateError(null);
    try {
      const res = await recordWhatsAppConsent({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone ?? "",
        source: "operator",
      });
      setThreadState((prev) =>
        prev
          ? { ...prev, opt_in_at: res.opt_in_at, opt_in_source: res.opt_in_source }
          : prev,
      );
    } catch (e) {
      setTemplateError(
        e instanceof Error ? e.message : "Could not record consent.",
      );
    }
  };

  // Debounce the search input so we don't refetch on every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const threadsQuery = useQuery({
    queryKey: ["inbox", "threads", debouncedSearch, showArchived],
    queryFn: async () => {
      const page = await fetchInboxThreads(debouncedSearch, showArchived);
      // Deep-link handling: if a thread was requested via URL, select it.
      const deep = deepLinkRef.current;
      if (deep.channel && deep.key) {
        const hit = page.threads.find(
          (t) => t.channel_id === deep.channel && t.key === deep.key,
        );
        if (hit) {
          setSelectedKey(`${hit.channel_id}:${hit.key}`);
          deepLinkRef.current = { channel: null, key: null };
        }
      }
      return page;
    },
    staleTime: 15 * 1000,
  });

  // Sync server state into local state (preserves realtime/WS mutation paths).
  useEffect(() => {
    const page = threadsQuery.data;
    if (page) {
      setThreads(page.threads);
      setNextThreadCursor(page.next_cursor);
      setLoading(false);
      setError(null);
    }
  }, [threadsQuery.data]);
  useEffect(() => {
    if (threadsQuery.isError) {
      setError(threadsQuery.error instanceof Error ? threadsQuery.error.message : "Could not load conversations.");
      setThreads([]);
      setLoading(false);
    }
  }, [threadsQuery.isError, threadsQuery.error]);

  const selected = useMemo(
    () => threads.find((t) => `${t.channel_id}:${t.key}` === selectedKey) ?? null,
    [threads, selectedKey],
  );

  // Message toasts mute themselves for the thread the agent is reading.
  useEffect(() => {
    setActiveThread(selectedKey);
  }, [selectedKey]);

  // The two-pane layout only exists from lg up. Below that the list is the
  // first screen and the chat opens on selection; auto-selecting the first
  // thread here would make the back button look dead because it immediately
  // reselects that thread.
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");
    const apply = () => setIsMobile(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const effectiveSelected = useMemo(() => {
    if (selected) return selected;
    if (isMobile) return null;
    if (threads.length === 0) return null;
    return threads.find((t) => !t.is_unknown) ?? threads[0];
  }, [selected, threads, isMobile]);

  const requestedKey = useRef<string | null>(null);
  const target = effectiveSelected;
  const targetKey = target ? `${target.channel_id}:${target.key}` : null;
  // The thread state is authoritative while the open thread is the loaded
  // one; the list row is the fallback before the messages call returns.
  const activeMode: "ai" | "human" =
    threadState?.mode ?? target?.mode ?? "ai";
  // Meta's window is per conversation. Once it closes a free-form reply is
  // rejected, so the composer steps aside for the template picker.
  const windowClosed =
    (target?.platform ?? "").toLowerCase() === "whatsapp" &&
    loadedKey === targetKey &&
    threadState?.reply_window_open === false;  const approvedTemplates = useMemo(
    () =>
      (templates ?? []).filter(
        (t) => t.status === "approved" && t.category === "utility",
      ),
    [templates],
  );
  const selectedTemplate = approvedTemplates.find((t) => t.id === templateId) ?? null;
  // Eligible owners for the open conversation. Fetched per channel because
  // channel access is per teammate; the picker never offers someone who
  // cannot open the thread.
  const assigneesQuery = useQuery({
    queryKey: ["inbox", "assignees", target?.channel_id ?? ""],
    queryFn: () => fetchAssignees(target!.channel_id),
    enabled: !!target && !target.is_unknown,
    staleTime: 60_000,
  });
  const assignees = assigneesQuery.data ?? [];
  const currentAssignee = threadState?.assigned_to ?? target?.assigned_to ?? null;
  const currentAssigneeName = threadState?.assignee_name ?? target?.assignee_name ?? null;
  const assigneeNotInList =
    !!currentAssignee &&
    !assignees.some((a) => a.user_id === currentAssignee);
  const targetKeyRef = useRef<string | null>(null);
  useEffect(() => {
    targetKeyRef.current = targetKey;
  }, [targetKey]);

  useInboxRealtime((e: InboxRealtimeEvent) => {
    if (e.type === "status" && e.message_id) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === e.message_id && e.status
            ? { ...m, status: e.status, error: e.error ?? m.error }
            : m,
        ),
      );
      return;
    }
    // Server-pushed AI composing state. Handled before the message guard
    // below, which requires an id and would drop this.
    if (e.type === "typing" && e.channel_id) {
      setAiTyping(e.channel_id, e.contact_phone ?? UNKNOWN_THREAD_KEY, e.typing !== false);
      return;
    }
    // Another tab assigned (or unassigned) the conversation. Update the row
    // and, when it is the open thread, the owner picker itself.
    if (e.type === "assignment" && e.channel_id) {
      const key = e.contact_phone ?? UNKNOWN_THREAD_KEY;
      const composite = `${e.channel_id}:${key}`;
      const patch = {
        assigned_to: e.assigned_to ?? null,
        assigned_at: e.assigned_at ?? null,
        assignee_name: e.assignee_name ?? null,
      };
      setThreads((prev) =>
        prev.map((t) =>
          `${t.channel_id}:${t.key}` === composite ? { ...t, ...patch } : t,
        ),
      );
      if (composite === targetKeyRef.current) {
        setThreadState((prev) => (prev ? { ...prev, ...patch } : prev));
      }
      return;
    }
    // Another tab switched the conversation between AI and human. Update the
    // row and, when it is the open thread, the mode switch itself.
    if (e.type === "mode" && e.channel_id) {
      const key = e.contact_phone ?? UNKNOWN_THREAD_KEY;
      const composite = `${e.channel_id}:${key}`;
      if (e.mode) {
        setThreads((prev) =>
          prev.map((t) =>
            `${t.channel_id}:${t.key}` === composite
              ? {
                  ...t,
                  mode: e.mode,
                  mode_changed_at: e.mode_changed_at ?? t.mode_changed_at,
                  mode_changed_by: e.mode_changed_by ?? t.mode_changed_by,
                }
              : t,
          ),
        );
        if (composite === targetKeyRef.current) {
          // A system event carries the escalation clock; a manual change on
          // another tab cleared it (resume_lead or takeover), so fall back to
          // the defaults rather than leaving a stale countdown on screen.
          const withClock = e.priority !== undefined;
          setThreadState((prev) => ({
            ...(prev ?? {
              mode: e.mode!,
              mode_changed_at: null,
              mode_changed_by: null,
              context: null,
            }),
            mode: e.mode!,
            mode_changed_at: e.mode_changed_at ?? prev?.mode_changed_at ?? null,
            mode_changed_by: e.mode_changed_by ?? prev?.mode_changed_by ?? null,
            priority: withClock ? e.priority : "normal",
            ai_miss_count: withClock ? e.ai_miss_count ?? 0 : 0,
            priority_since: withClock ? e.priority_since ?? null : null,
            escalated_at: withClock ? e.escalated_at ?? null : null,
            escalation_reminder_at: withClock
              ? e.escalation_reminder_at ?? null
              : null,
            handover_sent_at: withClock ? e.handover_sent_at ?? null : null,
            resume_at: withClock ? e.resume_at ?? null : null,
            escalation_resume_hours: withClock
              ? e.escalation_resume_hours ?? 24
              : 24,
          }));
        }
      }
      return;
    }
    if (e.type === "blocked" && e.channel_id) {
      const key = e.contact_phone ?? UNKNOWN_THREAD_KEY;
      const composite = `${e.channel_id}:${key}`;
      if (composite === targetKeyRef.current) {
        setThreadState((prev) =>
          prev
            ? {
                ...prev,
                blocked_at: e.blocked_at ?? null,
                blocked_by: e.blocked_by ?? null,
              }
            : prev,
        );
      }
      return;
    }
    if (e.type !== "message" || !e.channel_id || !e.id) return;
    const contactKey = e.contact_phone ?? UNKNOWN_THREAD_KEY;
    const composite = `${e.channel_id}:${contactKey}`;
    const open = composite === targetKeyRef.current;
    // An outbound message means whatever reply was pending has landed, on
    // either side. An inbound one means we are now waiting on the reply.
    if (e.direction === "outbound") clearThreadTyping(e.channel_id, contactKey);
    else setCustomerAwaiting(e.channel_id, contactKey);
    const msg: InboxMessage = {
      id: e.id,
      channel_id: e.channel_id,
      platform_message_id: null,
      direction: e.direction ?? "inbound",
      content: e.content ?? "",
      content_type: e.content_type ?? "text",
      status: e.status ?? "delivered",
      error: e.error ?? null,
      contact_phone: e.contact_phone ?? null,
      contact_name: e.contact_name ?? null,
      reply_to_message_id: e.reply_to_message_id ?? null,
      media_url: e.media_url ?? null,
      media_mime_type: e.media_mime_type ?? null,
      media_filename: e.media_filename ?? null,
      created_at: e.created_at ?? new Date().toISOString(),
    };
    if (open) {
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        const next = [...prev, msg];
        return next.length > INBOX_MESSAGE_BUFFER_CAP
          ? next.slice(next.length - INBOX_MESSAGE_BUFFER_CAP)
          : next;
      });
    }
    setThreads((prev) => {
      const idx = prev.findIndex((t) => `${t.channel_id}:${t.key}` === composite);
      if (idx === -1) {
        const fresh: InboxThread = {
          key: contactKey,
          contact_phone: e.contact_phone ?? null,
          display_name: e.contact_name ?? e.contact_phone ?? null,
          username: null,
          avatar_url: null,
          channel_id: e.channel_id!,
          channel_name: null,
          platform: e.platform ?? null,
          last_message: msg.content,
          last_message_at: msg.created_at,
          last_direction: msg.direction,
          message_count: 1,
          unread: msg.direction === "inbound" && !open ? 1 : 0,
          is_unknown: !e.contact_phone,
          can_reply: (e.platform ?? "") !== "google_reviews",
        };
        return [fresh, ...prev];
      }
      const t = prev[idx];
      const updated: InboxThread = {
        ...t,
        display_name: t.display_name ?? e.contact_name ?? null,
        last_message: msg.content,
        last_message_at: msg.created_at,
        last_direction: msg.direction,
        message_count: t.message_count + 1,
        unread: msg.direction === "inbound" && !open ? t.unread + 1 : open ? 0 : t.unread,
      };
      return [updated, ...prev.filter((_, i) => i !== idx)];
    });
  });

  useEffect(() => {
    requestedKey.current = targetKey;
    if (!target) return;
    let cancelled = false;
    setThreadState(null);
    setNextCursor(null);
    setLoadingEarlier(false);
    setEarlierError(null);
    setHistoryLimitReached(false);
    prependScrollRef.current = null;
    skipAutoScrollRef.current = false;
    (async () => {
      try {
        const data = await fetchThreadMessages(target.channel_id, target.contact_phone);
        if (!cancelled && requestedKey.current === targetKey) {
          setMessages(data.messages);
          setNextCursor(data.next_cursor);
          setThreadState(data.thread);
          setLoadedKey(targetKey);
        }
      } catch (e) {
        if (!cancelled && requestedKey.current === targetKey) {
          setMessages([]);
          setNextCursor(null);
          setThreadState(null);
          setReplyTo(null);
          setReactingTo(null);
          setRichComposer(null);
          setLoadedKey(targetKey);
          setError(e instanceof Error ? e.message : "Could not load this conversation.");
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  // Typing state for the open thread, read reactively so the row appears and
  // disappears without touching `messages`.
  const typingSource = useTypingSource(
    target?.channel_id,
    target?.key ?? null,
  );

  // Older pages prepend above the viewport. Restore the previous offset
  // before paint, then let the passive effect below skip its next bottom jump.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const anchor = prependScrollRef.current;
    if (!el || !anchor) return;
    el.scrollTop = el.scrollHeight - anchor.height + anchor.top;
    prependScrollRef.current = null;
  }, [messages.length]);

  useEffect(() => {
    if (skipAutoScrollRef.current) {
      skipAutoScrollRef.current = false;
      return;
    }
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    // typingSource is in the deps because the indicator renders below the
    // message list and would otherwise be left below the fold.
  }, [messages.length, targetKey, typingSource]);

  useEffect(() => {
    setPhotoOpen(false);
  }, [selectedKey]);

  useEffect(() => {
    if (!photoOpen) return;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPhotoOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [photoOpen]);

  const platformsPresent = useMemo(() => {
    const set = new Set<string>();
    for (const t of threads) if (t.platform) set.add(t.platform);
    return [...set];
  }, [threads]);

  const channelsQuery = useQuery({
    queryKey: ["inbox", "connected-channels"],
    queryFn: async () => {
      const data = (await apiFetch("/api/v1/channels")) as {
        channels?: { platform?: string; status?: string }[];
      };
      return (data.channels ?? [])
        .filter((c) => c.status === "active" && c.platform)
        .map((c) => c.platform as string);
    },
    staleTime: 60_000,
  });

  const connectedPlatforms = useMemo(() => {
    const present = new Set(channelsQuery.data ?? platformsPresent);
    const order = ["whatsapp", "google_reviews", "google", "facebook", "instagram"];
    const seenLabels = new Set<string>();
    return order.filter((p) => {
      if (!present.has(p)) return false;
      const label = platformMeta(p).label;
      if (seenLabels.has(label)) return false;
      seenLabels.add(label);
      return true;
    });
  }, [channelsQuery.data, platformsPresent]);

  const visible = useMemo(() => {
    let rows = threads;
    if (!showArchived) rows = rows.filter((t) => !t.archived);
    if (filter === "unread") rows = rows.filter((t) => t.unread > 0);
    if (filter === "important") rows = rows.filter((t) => t.important);
    if (filter === "mine") rows = rows.filter((t) => !!user && t.assigned_to === user.id);
    if (filter === "unknown") rows = rows.filter((t) => t.is_unknown);
    if (platformFilter !== "all") rows = rows.filter((t) => t.platform === platformFilter);
    return [...rows].sort((a, b) => {
      const ap = a.pinned ? 0 : 1;
      const bp = b.pinned ? 0 : 1;
      return ap - bp;
    });
  }, [threads, filter, platformFilter, showArchived]);

  const loadMoreThreads = async () => {
    if (!nextThreadCursor || loadingMoreThreads) return;
    setLoadingMoreThreads(true);
    try {
      const page = await fetchInboxThreads(debouncedSearch, showArchived, {
        cursor: nextThreadCursor,
      });
      setThreads((prev) => {
        const seen = new Set(prev.map((t) => `${t.channel_id}:${t.key}`));
        return [
          ...prev,
          ...page.threads.filter(
            (t) => !seen.has(`${t.channel_id}:${t.key}`),
          ),
        ];
      });
      setNextThreadCursor(page.next_cursor);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load more conversations.",
      );
    } finally {
      setLoadingMoreThreads(false);
    }
  };

  // Virtualize the thread list so a tenant with thousands of conversations
  // doesn't render thousands of DOM nodes. The scroll container is the
  // overflow-y-auto div below; rows are absolutely positioned by offset.
  const threadListRef = useRef<HTMLDivElement>(null);
  const threadVirtualizer = useVirtualizer({
    count: visible.length,
    getScrollElement: () => threadListRef.current,
    estimateSize: () => 76,
    overscan: 6,
  });

  const unreadTotal = useMemo(() => threads.reduce((s, t) => s + t.unread, 0), [threads]);
  const importantTotal = useMemo(
    () => threads.filter((t) => t.important).length,
    [threads],
  );
  const mineTotal = useMemo(
    () => (user ? threads.filter((t) => t.assigned_to === user.id).length : 0),
    [threads, user],
  );

  const threadView = useMemo(() => {
    const q = threadQuery.trim().toLowerCase();
    if (!q) return messages;
    return messages.filter((m) => m.content.toLowerCase().includes(q));
  }, [messages, threadQuery]);

  const loadEarlierMessages = async () => {
    if (!target || !nextCursor || loadingEarlier) return;
    if (messages.length >= INBOX_MESSAGE_BUFFER_CAP) {
      setHistoryLimitReached(true);
      return;
    }
    const keyAtStart = targetKey;
    setLoadingEarlier(true);
    setEarlierError(null);
    try {
      const data = await fetchThreadMessages(
        target.channel_id,
        target.contact_phone,
        { before: nextCursor },
      );
      if (requestedKey.current !== keyAtStart) return;
      const seen = new Set(messages.map((m) => m.id));
      const older = data.messages.filter((m) => !seen.has(m.id));
      const room = Math.max(0, INBOX_MESSAGE_BUFFER_CAP - messages.length);
      const take = older.slice(Math.max(0, older.length - room));
      const truncated =
        take.length < older.length ||
        (take.length === room && Boolean(data.next_cursor));
      if (take.length > 0) {
        const el = scrollRef.current;
        if (el) {
          prependScrollRef.current = {
            height: el.scrollHeight,
            top: el.scrollTop,
          };
          skipAutoScrollRef.current = true;
        }
        setMessages((prev) => {
          const current = new Set(prev.map((m) => m.id));
          const add = take.filter((m) => !current.has(m.id));
          return add.length > 0 ? [...add, ...prev] : prev;
        });
      }
      setNextCursor(truncated ? null : data.next_cursor);
      setHistoryLimitReached(truncated);
    } catch (e) {
      if (requestedKey.current === keyAtStart) {
        setEarlierError(
          e instanceof Error ? e.message : "Could not load earlier messages.",
        );
      }
    } finally {
      setLoadingEarlier(false);
    }
  };

  const send = async () => {
    const text = draft.trim();
    const thread = target;
    if (!text || !thread || sending) return;
    setSending(true);
    setSendError(null);
    try {
      const result = await sendInboxMessage({
        channelId: thread.channel_id,
        contactPhone: thread.contact_phone ?? "",
        contactName: thread.display_name,
        content: text,
        replyToMessageId: replyTo?.id ?? null,
      });
      // A rejected message is still rendered so the user can see what Meta
      // refused. It is not accepted as sent and must not consume their draft.
      setMessages((prev) =>
        prev.some((m) => m.id === result.message.id) ? prev : [...prev, result.message],
      );
      if (result.sent) {
        setDraft("");
        setReplyTo(null);
        // The agent answered, so nothing is pending on either side. The realtime
        // socket would clear this too, but a failed send never produces an
        // outbound event — clear here so a rejected message cannot strand dots.
        clearThreadTyping(thread.channel_id, thread.key);
        setThreads((prev) =>
          prev.map((t) =>
            `${t.channel_id}:${t.key}` === `${thread.channel_id}:${thread.key}`
              ? {
                  ...t,
                  unread: 0,
                  last_message: result.message.content,
                  last_message_at: result.message.created_at,
                  last_direction: "outbound",
                  message_count: t.message_count + 1,
                }
              : t,
          ),
        );
      } else {
        setSendError(
          result.error ||
            (thread.platform === "instagram"
              ? "Instagram rejected this message."
              : "WhatsApp rejected this message."),
        );
      }
    } catch {
      setSendError("Couldn't send the message. Check your connection and try again.");
    } finally {
      setSending(false);
    }
  };

  // `can_reply === false` (not `!can_reply`) so a thread from an older
  // API — which does not send the field — can still be replied to.
  const canSend =
    !!target && !target.is_unknown && target.can_reply !== false && replyWindowOpen(target) && !!draft.trim() && !sending;
  const openThread = !!target;

  return (
    <div className="flex h-full flex-col p-4 sm:p-6">
      {(!isMobile || !openThread) && (
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog sm:text-[20px]">Inbox</h1>
            <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45 sm:text-[13px]">
              Every conversation across your connected numbers.
            </p>
          </div>
          <button
            onClick={() => void queryClient.invalidateQueries({ queryKey: ["inbox", "threads"] })}
            className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          >
            Refresh
          </button>
        </div>
      )}
      {listActionError && (
        <div
          role="alert"
          className="mb-3 flex items-center justify-between gap-4 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[12px] font-medium text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
        >
          <span>{listActionError}</span>
          <button
            type="button"
            onClick={() => setListActionError(null)}
            className="min-h-[44px] shrink-0 rounded-lg px-3 font-semibold underline underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className={`relative grid min-h-0 flex-1 gap-4 ${showInfo ? "lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)_minmax(0,280px)]" : "lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]"}`}>
        {/* Thread list */}
        <div className={`${openThread ? "hidden lg:flex" : "flex"} min-h-0 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink`}>
          <div className="border-b border-ink/[0.06] p-3 dark:border-fog/[0.06]">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search conversations"
              aria-label="Search conversations"
              className="input-field w-full"
            />
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {([
                { key: "all", label: "All" },
                { key: "unread", label: `Unread${unreadTotal ? ` (${unreadTotal})` : ""}` },
                { key: "important", label: `Important${importantTotal ? ` (${importantTotal})` : ""}` },
                { key: "mine", label: `Mine${mineTotal ? ` (${mineTotal})` : ""}` },
                { key: "unknown", label: "Unknown" },
              ] as { key: Filter; label: string }[]).map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  aria-pressed={filter === f.key}
                  className={`rounded-lg px-2 py-1 text-[11px] font-semibold transition ${
                    filter === f.key ? "bg-deep-violet/10 text-deep-violet" : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
                  }`}
                >
                  {f.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setShowArchived((v) => !v)}
                aria-pressed={showArchived}
                className={`rounded-lg border px-2 py-1 text-[11px] font-semibold transition ${
                  showArchived
                    ? "border-deep-violet bg-deep-violet/10 text-deep-violet"
                    : "border-ink/[0.08] bg-white text-ink/60 hover:text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
                }`}
              >
                {showArchived ? "Hide archived" : "Show archived"}
              </button>
              <select
                value={platformFilter}
                onChange={(e) => setPlatformFilter(e.target.value)}
                aria-label="Filter by platform"
                className="ml-auto rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                <option value="all">All platforms</option>
                {platformsPresent.map((p) => (
                  <option key={p} value={p}>
                    {platformMeta(p).label}
                  </option>
                ))}
              </select>
            </div>
            {connectedPlatforms.length > 0 && (
              <div className="mt-2 flex items-center gap-1.5 overflow-x-auto border-t border-ink/[0.05] pt-2 dark:border-fog/[0.06]">
                <button
                  type="button"
                  onClick={() => setPlatformFilter("all")}
                  aria-pressed={platformFilter === "all"}
                  className={`shrink-0 rounded-lg border px-2 py-1 text-[10px] font-bold uppercase tracking-wide transition ${
                    platformFilter === "all"
                      ? "border-deep-violet bg-deep-violet/10 text-deep-violet"
                      : "border-ink/[0.08] bg-white text-ink/45 hover:text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog/45"
                  }`}
                >
                  All
                </button>
                {connectedPlatforms.map((p) => {
                  const meta = platformMeta(p);
                  const active = platformFilter === p;
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setPlatformFilter(active ? "all" : p)}
                      aria-pressed={active}
                      title={meta.label}
                      className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1 text-[10px] font-semibold transition ${
                        active
                          ? "border-deep-violet bg-deep-violet/10 text-deep-violet"
                          : "border-ink/[0.08] bg-white text-ink/50 hover:text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog/50"
                      }`}
                    >
                      {meta.icon && (
                        <Image
                          src={meta.icon}
                          alt=""
                          width={14}
                          height={14}
                          className="h-3.5 w-3.5 rounded-full"
                        />
                      )}
                      <span>{meta.label.replace(" Messenger", "")}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div ref={threadListRef} className="min-h-0 flex-1 overflow-y-auto">
            {loading && threads.length === 0 ? (
              <div className="flex justify-center py-16"><LogoLoader size={28} /></div>
            ) : visible.length === 0 ? (
              <p className="px-4 py-10 text-center text-[12px] text-ink/40">
                {search ? "No conversations match that search." : "No messages yet. Once customers message your number they appear here."}
              </p>
            ) : (
              <div style={{ height: threadVirtualizer.getTotalSize(), position: "relative", width: "100%" }}>
                {threadVirtualizer.getVirtualItems().map((vi) => {
                  const t = visible[vi.index];
                  const composite = `${t.channel_id}:${t.key}`;
                  const active = composite === targetKey;
                  const isPinned = !!t.pinned;
                  return (
                    <div key={composite} data-index={vi.index} ref={threadVirtualizer.measureElement} style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}>
                      <div className={`flex items-start border-b border-ink/[0.04] dark:border-fog/[0.04] ${active ? "bg-deep-violet/[0.06]" : "hover:bg-ink/[0.02] dark:hover:bg-fog/[0.03]"}`}>
                        <button
                          onClick={() => {
                            setSelectedKey(composite);
                            setShowInfo(false);
                            setSendError(null);
                          }}
                          aria-current={active}
                          className="flex min-w-0 flex-1 items-start gap-3 px-3.5 py-4 text-left"
                        >
                          <Avatar
                            name={t.display_name}
                            phone={t.contact_phone}
                            url={t.avatar_url}
                            boxCls="h-10 w-10 rounded-full bg-deep-violet/10 text-[12px] text-deep-violet"
                          >
                            <PlatformBadge platform={t.platform} />
                          </Avatar>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-baseline justify-between gap-2">
                              <span className="flex min-w-0 items-center gap-1.5">
                                <span className="truncate text-[13.5px] font-semibold text-ink dark:text-fog">
                                  {t.display_name || "Unknown sender"}
                                </span>
                                {t.lead_category && (
                                  <span className="shrink-0 rounded-full border border-ink/[0.08] px-1.5 py-0.5 text-[9px] font-semibold text-ink/60 dark:border-fog/[0.12] dark:text-fog/60">
                                    {leadCategoryLabel(t.lead_category)}
                                  </span>
                                )}
                                {t.assigned_to && (
                                  <span
                                    title={
                                      t.assigned_to === user?.id
                                        ? "Assigned to you"
                                        : `Assigned to ${t.assignee_name ?? "a teammate"}`
                                    }
                                    className="shrink-0 text-[9px] font-semibold text-ink/40 dark:text-fog/40"
                                  >
                                    {t.assigned_to === user?.id
                                      ? "You"
                                      : t.assignee_name ?? "Assigned"}
                                  </span>
                                )}
                                {t.important && (
                                  <span
                                    className="shrink-0 rounded-full bg-[#FF4F6E]/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[#C4304B] dark:bg-[#FF4F6E]/20 dark:text-[#FF8FA3]"
                                    title={importantReason(t)}
                                  >
                                    Important
                                  </span>
                                )}
                              </span>
                              <span className="shrink-0 text-[11px] text-ink/35 dark:text-fog/35">
                                {relative(t.last_message_at)}
                              </span>
                            </span>
                            {(t.platform === "google_reviews" || t.platform === "google") && (
                              <span
                                className="mt-0.5 flex min-w-0 items-center gap-1 text-[10.5px] font-medium text-ink/40 dark:text-fog/40"
                                title={t.channel_name ?? "Google review"}
                              >
                                <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-3 w-3 shrink-0">
                                  <path d="M12 21s7-5.4 7-11a7 7 0 1 0-14 0c0 5.6 7 11 7 11Z" stroke="currentColor" strokeWidth={1.5} />
                                  <circle cx="12" cy="10" r="2.2" stroke="currentColor" strokeWidth={1.5} />
                                </svg>
                                <span className="truncate">
                                  {t.channel_name ?? "Google review"}
                                </span>
                              </span>
                            )}
                            <span className="mt-1 flex items-center gap-1.5">
                              <span className="truncate text-[12.5px] text-ink/50 dark:text-fog/50">
                                {t.last_direction === "outbound" ? "You: " : ""}
                                {t.last_message}
                              </span>
                              {t.unread > 0 && (
                                <span className="ml-auto shrink-0 rounded-full bg-deep-violet px-1.5 text-[10px] font-bold text-white" aria-label={`${t.unread} unread`}>
                                  {t.unread}
                                </span>
                              )}
                            </span>
                          </span>
                        </button>
                        <button
                          onClick={() => togglePin(t)}
                          aria-label={isPinned ? "Unpin thread" : "Pin thread"}
                          className={`px-2 py-4 text-[13px] ${isPinned ? "text-deep-violet" : "text-ink/20 hover:text-ink/50"}`}
                        >
                          📌
                        </button>
                        <button
                          onClick={() => void handleArchive(t, !t.archived)}
                          aria-label={t.archived ? "Unarchive thread" : "Archive thread"}
                          className={`px-2 py-4 text-[13px] ${t.archived ? "text-amber-600" : "text-ink/20 hover:text-ink/50"}`}
                          title={t.archived ? "Unarchive" : "Archive"}
                        >
                          {t.archived ? "📥" : "📦"}
                        </button>
                        <button
                          onClick={() => {
                            setListActionError(null);
                            setDeleteTarget(t);
                          }}
                          aria-label="Delete thread"
                          className="px-2 py-4 text-[13px] text-ink/20 hover:text-red-600"
                          title="Delete conversation permanently"
                        >
                          🗑
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {nextThreadCursor && (
              <div className="border-t border-ink/[0.04] p-3 text-center dark:border-fog/[0.04]">
                <button
                  type="button"
                  onClick={() => void loadMoreThreads()}
                  disabled={loadingMoreThreads}
                  className="rounded-full border border-ink/[0.08] bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/60 dark:hover:text-fog"
                >
                  {loadingMoreThreads
                    ? "Loading…"
                    : "Load more conversations"}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Thread detail */}
        <div className={`${openThread ? "flex" : "hidden lg:flex"} min-h-0 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink`}>
          {!target ? (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ink/40">
              Select a conversation to read it.
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 border-b border-ink/[0.06] bg-white/95 px-4 py-3.5 dark:border-fog/[0.06] dark:bg-ink/95">
                <button
                  onClick={() => {
                    setSelectedKey(null);
                    setShowInfo(false);
                  }}
                  aria-label="Back to conversations"
                  className="rounded-lg px-2 py-1 text-[13px] font-semibold text-deep-violet lg:hidden"
                >
                  ← Back
                </button>
                <button
                  onClick={() => setShowInfo((v) => !v)}
                  className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-xl p-1.5 text-left transition hover:bg-ink/[0.04] dark:hover:bg-fog/[0.05]"
                  aria-label="View contact profile"
                >
                  <Avatar
                    name={target.display_name}
                    phone={target.contact_phone}
                    url={target.avatar_url}
                    boxCls="h-11 w-11 rounded-full bg-deep-violet/10 text-[12px] text-deep-violet ring-1 ring-deep-violet/10"
                  >
                    <PlatformBadge platform={target.platform} />
                  </Avatar>
                  <span className="min-w-0 flex-1">
                    <p className="flex min-w-0 items-center gap-1.5 text-[15px] font-semibold text-ink dark:text-fog">
                      <span className="truncate">
                        {target.display_name || "Unknown sender"}
                      </span>
                      {(threadState?.lead_category ?? target.lead_category) && (
                        <span className="shrink-0 rounded-full border border-ink/[0.08] px-1.5 py-0.5 text-[9px] font-semibold text-ink/55 dark:border-fog/[0.12] dark:text-fog/55">
                          {leadCategoryLabel(
                            threadState?.lead_category ?? target.lead_category,
                          )}
                        </span>
                      )}
                    </p>
                    <p className="truncate text-[12px] text-ink/45 dark:text-fog/45">
                      {/* A Google reviewer has no phone number - show the location. */}
                      {target.platform === "google_reviews" || target.platform === "google"
                        ? target.channel_name ?? "Google review"
                        : target.platform === "instagram"
                          ? target.contact_phone
                          : formatPhone(target.contact_phone)}
                      {target.channel_name && target.platform !== "google_reviews" && target.platform !== "google" ? ` · ${target.channel_name}` : ""}
                    </p>
                  </span>
                </button>
                {!target.is_unknown && (
                  <label className="hidden shrink-0 items-center gap-1.5 md:flex">
                    <span className="text-[9px] font-bold uppercase tracking-wide text-ink/35 dark:text-fog/35">
                      Owner
                    </span>
                    <select
                      value={currentAssignee ?? ""}
                      onChange={(e) =>
                        void handleAssignee(target, e.target.value || null)
                      }
                      disabled={assigneeBusy}
                      aria-label="Conversation owner"
                      className="h-7 max-w-[160px] rounded-full border border-ink/[0.08] bg-white px-2 text-[10px] font-semibold text-ink disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                    >
                      <option value="">Unassigned</option>
                      {assigneeNotInList && currentAssignee && (
                        <option value={currentAssignee}>
                          {currentAssigneeName ?? "Assigned"}
                        </option>
                      )}
                      {assignees.map((a) => (
                        <option key={a.user_id} value={a.user_id}>
                          {a.user_id === user?.id ? `${a.name} (you)` : a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {assigneeError && (
                  <span
                    role="alert"
                    className="text-[10px] font-medium text-[#C4304B] dark:text-[#FF8FA3]"
                  >
                    {assigneeError}
                  </span>
                )}
                {/* Who answers: the same switch the backend uses to mute the
                    AI. Segmented so both states are visible at once — a
                    toggle would hide the fact that a human took over. */}
                <div
                  role="group"
                  aria-label="Who answers this conversation"
                  className="ml-auto flex w-full shrink-0 items-center gap-0.5 rounded-full border border-ink/[0.08] bg-white p-0.5 sm:w-auto dark:border-fog/[0.12] dark:bg-ink"
                >
                  <button
                    type="button"
                    aria-pressed={activeMode === "ai"}
                    disabled={modeBusy}
                    onClick={() => void handleModeChange(target, "ai")}
                    title="The AI answers this conversation"
                    className={`flex-1 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide transition disabled:opacity-50 sm:flex-none ${
                      activeMode === "ai"
                        ? "bg-deep-violet text-white"
                        : "text-ink/45 hover:text-ink/70 dark:text-fog/45 dark:hover:text-fog/70"
                    }`}
                  >
                    AI
                  </button>
                  <button
                    type="button"
                    aria-pressed={activeMode === "human"}
                    disabled={modeBusy}
                    onClick={() => void handleModeChange(target, "human")}
                    title="A person answers; the AI stays silent"
                    className={`flex-1 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide transition disabled:opacity-50 sm:flex-none ${
                      activeMode === "human"
                        ? "bg-deep-violet text-white"
                        : "text-ink/45 hover:text-ink/70 dark:text-fog/45 dark:hover:text-fog/70"
                    }`}
                  >
                    Human
                  </button>
                </div>
                {target.is_unknown && (
                  <span className="hidden shrink-0 rounded-full bg-amber-100 px-2 py-1 text-[10px] font-bold text-amber-700 sm:inline">
                    Sender not recorded
                  </span>
                )}
              </div>

              {modeError && (
                <p
                  role="alert"
                  className="border-b border-ink/[0.04] px-4 py-2 text-[11px] font-medium text-[#C4304B] dark:border-fog/[0.04] dark:text-[#FF8FA3]"
                >
                  {modeError}
                </p>
              )}

              {/* Conversation state: an explicit human owner, and the stored
                  summary of what has happened so far. The summary is what the
                  AI resumes with, so the human reads the same page. */}
              {activeMode === "human" && (
                <div className="border-b border-ink/[0.04] bg-fog/60 dark:border-fog/[0.04] dark:bg-fog/[0.05]">
                  <div className="flex items-center gap-2 px-4 py-2">
                    <span className="rounded-full bg-deep-violet px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
                      Human
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[11px] text-ink/60 dark:text-fog/60">
                      The AI is paused on this conversation.
                      {threadState?.mode_changed_by === "system"
                        ? " It was escalated automatically."
                        : ""}
                    </span>
                    <button
                      type="button"
                      disabled={modeBusy}
                      onClick={() => void handleResolve(target)}
                      className="shrink-0 rounded-full border border-deep-violet/25 px-2.5 py-1 text-[10px] font-bold text-deep-violet transition hover:bg-deep-violet/10 disabled:opacity-50 dark:border-fog/20 dark:text-fog"
                    >
                      Resolve
                    </button>
                  </div>

                  {/* The escalation clock. The mode switch says the AI is
                      muted; this says why, whether the humans were told, and
                      exactly when the sweep will hand the thread back — so a
                      24h window cannot look like a dead bot. */}
                  {threadState?.priority === "important" && (
                    <div className="mx-3 mb-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-500/30 dark:bg-amber-500/10">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span
                          title={
                            threadState.handover_sent_at
                              ? "The customer was told a human is taking over."
                              : "The holding line has not been delivered to the customer."
                          }
                          className="rounded-full bg-amber-200/70 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-900 dark:bg-amber-400/20 dark:text-amber-200"
                        >
                          Escalated
                        </span>
                        <span className="text-[11px] font-medium text-amber-900 dark:text-amber-200">
                          {threadState.priority_since
                            ? ago(threadState.priority_since)
                            : "time unknown"}
                          {threadState.ai_miss_count
                            ? ` · ${threadState.ai_miss_count} missed ${
                                threadState.ai_miss_count === 1 ? "turn" : "turns"
                              }`
                            : " · flagged urgent"}
                        </span>
                        <button
                          type="button"
                          disabled={modeBusy}
                          onClick={() => void handleModeChange(target, "ai")}
                          title="Skip the scheduled resume and hand this thread back to the AI now."
                          className="ml-auto shrink-0 rounded-full bg-deep-violet px-3 py-1 text-[10px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
                        >
                          Resume AI now
                        </button>
                      </div>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-amber-900/80 dark:text-amber-200/80">
                        <span>{reminderLabel(threadState)}</span>
                        <span aria-hidden>·</span>
                        <span>
                          {threadState.resume_at
                            ? `AI resumes automatically ${remaining(threadState.resume_at)}`
                            : "No automatic resume scheduled"}
                        </span>
                        {threadState.resume_at && (
                          <>
                            <span aria-hidden>·</span>
                            <span>{threadState.escalation_resume_hours ?? 24}h window</span>
                          </>
                        )}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {threadState?.context && (
                <details
                  key={targetKey ?? "thread"}
                  open={activeMode === "human"}
                  className="border-b border-ink/[0.04] px-4 py-2 dark:border-fog/[0.04]"
                >
                  <summary className="cursor-pointer text-[10px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
                    Conversation context
                    <span className="ml-1.5 font-medium normal-case tracking-normal">
                      · {contextReasonLabel(threadState.context.reason)} ·{" "}
                      {relative(threadState.context.created_at)} ·{" "}
                      {threadState.context.message_count} messages
                    </span>
                  </summary>
                  <p className="mt-1.5 whitespace-pre-line text-[12px] leading-5 text-ink/70 dark:text-fog/70">
                    {threadState.context.summary}
                  </p>
                </details>
              )}

              <div className="border-b border-ink/[0.04] px-3 py-2 dark:border-fog/[0.04]">
                <input
                  value={threadQuery}
                  onChange={(e) => setThreadQuery(e.target.value)}
                  placeholder="Search in conversation…"
                  aria-label="Search in conversation"
                  className="input-field w-full"
                />
              </div>

              <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto bg-[#f7f6fa] px-4 py-5 dark:bg-[#0f0c18] sm:px-6">
                {loadedKey !== targetKey ? (
                  <div className="flex justify-center py-16"><LogoLoader size={24} /></div>
                ) : threadView.length === 0 ? (
                  <p className="py-10 text-center text-[12px] text-ink/40">
                    {threadQuery ? "No messages match." : "No messages."}
                  </p>
                ) : (
                  <>
                    {!threadQuery && nextCursor && !historyLimitReached && (
                      <div className="mb-3 flex justify-center">
                        <button
                          type="button"
                          disabled={loadingEarlier}
                          onClick={() => void loadEarlierMessages()}
                          className="rounded-full border border-ink/[0.08] bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/55 transition hover:border-deep-violet/30 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/55 dark:hover:text-fog"
                        >
                          {loadingEarlier ? "Loading earlier…" : "Load earlier messages"}
                        </button>
                      </div>
                    )}
                    {!threadQuery && historyLimitReached && (
                      <p className="mb-3 text-center text-[10px] text-ink/40 dark:text-fog/40">
                        Showing the latest {INBOX_MESSAGE_BUFFER_CAP} messages.
                      </p>
                    )}
                    {!threadQuery && earlierError && (
                      <p
                        role="alert"
                        className="mb-3 text-center text-[11px] font-medium text-[#C4304B] dark:text-[#FF8FA3]"
                      >
                        {earlierError}
                      </p>
                    )}
                    {threadView.map((m, i) => {
                    const showDay =
                      i === 0 ||
                      new Date(threadView[i - 1].created_at).toDateString() !== new Date(m.created_at).toDateString();
                    const mine = m.direction === "outbound";
                    const previous = threadView[i - 1];
                    const firstInRun =
                      !previous ||
                      previous.direction !== m.direction ||
                      new Date(m.created_at).getTime() -
                        new Date(previous.created_at).getTime() >
                        5 * 60 * 1000;
                    const quotedMessage = m.reply_to_message_id
                      ? messages.find(
                          (x) => x.platform_message_id === m.reply_to_message_id,
                        ) ?? null
                      : null;
                    const mediaSrc = resolveMediaUrl(m.media_url);
                    const isImageAttachment =
                      !!mediaSrc &&
                      (m.content_type === "image" || m.content_type === "sticker");
                    const isDocumentAttachment =
                      !!mediaSrc && m.content_type === "document";
                    const isPlaceholder = /^\[[a-z]+ message\]$/.test(m.content);
                    const missingMediaLabel =
                      m.content_type === "image"
                        ? "Image attachment could not be loaded"
                        : m.content_type === "document"
                          ? "Document attachment could not be loaded"
                          : m.content_type === "sticker"
                            ? "Sticker could not be loaded"
                            : m.content_type === "video"
                              ? "Video message"
                              : m.content;
                    const attachmentText =
                      m.content_type === "sticker" && mediaSrc
                        ? ""
                        : isDocumentAttachment && m.content === m.media_filename
                          ? ""
                          : isPlaceholder
                            ? mediaSrc
                              ? ""
                              : missingMediaLabel
                            : m.content;
                    if (m.content_type === "reaction") {
                      if (!m.content) return null;
                      const emoji = m.content.startsWith("[") ? "👍" : m.content;
                      return (
                        <div key={m.id}>
                          {showDay && (
                            <p className="my-3 text-center text-[11px] font-semibold text-ink/30 dark:text-fog/30">
                              {dayLabel(m.created_at)}
                            </p>
                          )}
                          <div className={`mb-2 flex ${mine ? "justify-end" : "justify-start"}`}>
                            <span
                              title={`Reacted ${clockTime(m.created_at)}`}
                              className="rounded-full bg-ink/[0.05] px-3 py-1 text-[20px] leading-7 dark:bg-fog/[0.08]"
                            >
                              {emoji}
                            </span>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div key={m.id} className="group">
                        {showDay && (
                          <p className="my-3 text-center text-[11px] font-semibold text-ink/30 dark:text-fog/30">
                            {dayLabel(m.created_at)}
                          </p>
                        )}
                        <div className={`mb-1.5 flex items-end gap-2 ${mine ? "justify-end" : "justify-start"}`}>
                          {!mine &&
                            (firstInRun ? (
                              <Avatar
                                name={target?.display_name ?? ""}
                                phone={target?.contact_phone ?? null}
                                url={target?.avatar_url}
                                boxCls="h-7 w-7 shrink-0 rounded-full bg-deep-violet/10 text-[9px] text-deep-violet ring-1 ring-deep-violet/10"
                              />
                            ) : (
                              <span className="h-7 w-7 shrink-0" aria-hidden />
                            ))}
                          <div
                            className={`max-w-[72%] rounded-2xl px-4 py-2.5 shadow-sm ${
                              mine
                                ? m.status === "failed"
                                  ? "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-200"
                                  : "bg-deep-violet text-white"
                                : "border border-ink/[0.06] bg-white text-ink dark:border-fog/[0.08] dark:bg-fog/[0.06] dark:text-fog"
                            }`}
                          >
                            {m.deleted ? (
                              <p className="text-[12px] italic opacity-60">
                                Message removed from this inbox
                              </p>
                            ) : (
                              <>
                                {quotedMessage && (
                                  <div
                                    className={`mb-1.5 rounded-lg border-l-2 px-2 py-1 ${
                                      mine
                                        ? "border-white/40 bg-white/10"
                                        : "border-deep-violet/30 bg-deep-violet/[0.06]"
                                    }`}
                                  >
                                    <p
                                      className={`text-[10px] font-bold ${
                                        mine
                                          ? "text-white/70"
                                          : "text-deep-violet/70 dark:text-fog/60"
                                      }`}
                                    >
                                      {quotedMessage.direction === "outbound"
                                        ? "You"
                                        : target?.display_name || "Customer"}
                                    </p>
                                    <p
                                      className={`truncate text-[11px] ${
                                        mine
                                          ? "text-white/70"
                                          : "text-ink/55 dark:text-fog/55"
                                      }`}
                                    >
                                      {quotedMessage.deleted
                                        ? "Message removed"
                                        : quotedMessage.media_url
                                          ? quotedMessage.media_filename ||
                                            (quotedMessage.content_type === "sticker"
                                              ? "Sticker"
                                              : "Attachment")
                                          : quotedMessage.content || "…"}
                                    </p>
                                  </div>
                                )}
                                {m.content_type === "location" ||
                                m.content_type === "contact" ||
                                m.content_type === "contacts" ? (
                                  <p
                                    className={`mb-1 text-[10px] font-bold uppercase tracking-wide ${
                                      mine
                                        ? "text-white/70"
                                        : "text-ink/45 dark:text-fog/45"
                                    }`}
                                  >
                                    {m.content_type === "location"
                                      ? "Location"
                                      : "Contact card"}
                                  </p>
                                ) : null}
                                {isImageAttachment && mediaSrc ? (
                                  <a
                                    href={mediaSrc}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="mb-1 block"
                                  >
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                      src={mediaSrc}
                                      alt={
                                        m.media_filename ||
                                        (m.content_type === "sticker"
                                          ? "Sticker"
                                          : "Image attachment")
                                      }
                                      className={
                                        m.content_type === "sticker"
                                          ? "h-32 w-32 object-contain"
                                          : "max-h-72 w-auto max-w-full rounded-lg object-contain"
                                      }
                                    />
                                  </a>
                                ) : null}
                                {isDocumentAttachment && mediaSrc ? (
                                  <a
                                    href={mediaSrc}
                                    target="_blank"
                                    rel="noreferrer"
                                    download={m.media_filename ?? undefined}
                                    className={`mb-1 flex max-w-full items-center gap-2 rounded-lg px-2.5 py-2 ${
                                      mine
                                        ? "bg-white/15 text-white"
                                        : "bg-white/70 text-ink dark:bg-ink/40 dark:text-fog"
                                    }`}
                                  >
                                    <span aria-hidden className="text-[18px]">📄</span>
                                    <span className="min-w-0 flex-1">
                                      <span className="block truncate text-[12px] font-semibold">
                                        {m.media_filename || "Document"}
                                      </span>
                                      <span
                                        className={`text-[10px] ${
                                          mine ? "text-white/70" : "text-ink/50 dark:text-fog/50"
                                        }`}
                                      >
                                        Download document
                                      </span>
                                    </span>
                                  </a>
                                ) : null}
                                {attachmentText ? (
                                  <p className="whitespace-pre-wrap break-words text-[13.5px] leading-5">
                                    {attachmentText}
                                  </p>
                                ) : null}
                              </>
                            )}
                            <p
                              className={`mt-1 flex items-center justify-end gap-1 text-[10.5px] ${
                                mine ? (m.status === "failed" ? "text-red-500" : "text-white/70") : "text-ink/35 dark:text-fog/35"
                              }`}
                            >
                              {clockTime(m.created_at)}
                              {mine && <StatusTick message={m} />}
                              {mine && m.status === "failed" ? " · not sent" : ""}
                            </p>
                            {mine && m.status === "failed" && m.error && (
                              <p className="mt-1 border-t border-red-200 pt-1 text-[11px] text-red-600 dark:border-red-900 dark:text-red-300">
                                {m.error}
                              </p>
                            )}
                          </div>
                        </div>
                        {!m.deleted && (
                          <div
                            className={`mb-2 flex items-center gap-1 opacity-100 transition sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100 ${
                              mine ? "justify-end" : "justify-start"
                            }`}
                          >
                            {target?.platform === "whatsapp" && (
                              <button
                                type="button"
                                onClick={() => setReplyTo(m)}
                                className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-ink/45 transition hover:bg-ink/[0.05] hover:text-ink dark:text-fog/45 dark:hover:bg-fog/[0.08] dark:hover:text-fog"
                              >
                                Reply
                              </button>
                            )}
                            {!mine && target?.platform === "whatsapp" && (
                              <button
                                type="button"
                                onClick={() =>
                                  setReactingTo(reactingTo === m.id ? null : m.id)
                                }
                                className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-ink/45 transition hover:bg-ink/[0.05] hover:text-ink dark:text-fog/45 dark:hover:bg-fog/[0.08] dark:hover:text-fog"
                              >
                                React
                              </button>
                            )}
                            {mine && (
                              <button
                                type="button"
                                onClick={() => void removeMessage(m)}
                                title="Removes it from this inbox only — the customer still has it."
                                className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-ink/45 transition hover:bg-red-50 hover:text-red-600 dark:text-fog/45 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                              >
                                Remove
                              </button>
                            )}
                          </div>
                        )}
                        {reactingTo === m.id && !mine && (
                          <div className="mb-2 flex justify-start gap-1">
                            {REACTION_EMOJIS.map((emoji) => (
                              <button
                                key={emoji}
                                type="button"
                                disabled={reactBusy}
                                onClick={() => void react(m, emoji)}
                                aria-label={`React with ${emoji}`}
                                className="rounded-full border border-ink/[0.08] bg-white px-2 py-1 text-[16px] leading-5 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink"
                              >
                                {emoji}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                    })}
                  </>
                )}
                {typingSource && loadedKey === targetKey && (
                  <TypingIndicator
                    source={typingSource}
                    contactName={target?.display_name}
                  />
                )}
              </div>

              <div className="border-t border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                {sendError && (
                  <p role="status" className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:bg-red-950/40 dark:text-red-300">
                    {sendError}
                  </p>
                )}
                {replyTo && (
                  <div className="mb-2 flex items-start gap-2 rounded-xl border-l-2 border-deep-violet bg-deep-violet/[0.05] px-3 py-2 dark:bg-fog/[0.06]">
                    <div className="min-w-0 flex-1">
                      <p className="text-[9px] font-bold uppercase tracking-wide text-deep-violet/70 dark:text-fog/60">
                        Replying to{" "}
                        {replyTo.direction === "outbound"
                          ? "your message"
                          : target?.display_name || "the customer"}
                      </p>
                      <p className="truncate text-[11px] text-ink/60 dark:text-fog/60">
                        {replyTo.content || "…"}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setReplyTo(null)}
                      aria-label="Cancel reply"
                      className="shrink-0 rounded-full px-1.5 text-[14px] leading-5 text-ink/40 hover:text-ink dark:text-fog/40 dark:hover:text-fog"
                    >
                      ×
                    </button>
                  </div>
                )}
                <div className="mb-2 flex gap-1.5 overflow-x-auto">
                  {QUICK_REPLIES.map((q) => (
                    <button
                      key={q}
                      onClick={() => setDraft(q)}
                      className="shrink-0 rounded-full border border-ink/[0.08] px-2.5 py-1 text-[11px] text-ink/60 transition hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:text-fog/60"
                    >
                      {q}
                    </button>
                  ))}
                </div>
                {target?.platform === "whatsapp" && (
                  <div className="mb-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => openRichComposer("location")}
                      className="rounded-full border border-ink/[0.08] px-2.5 py-1 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:text-fog/60"
                    >
                      📍 Send location
                    </button>
                    <button
                      type="button"
                      onClick={() => openRichComposer("contact")}
                      className="rounded-full border border-ink/[0.08] px-2.5 py-1 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:text-fog/60"
                    >
                      👤 Send contact
                    </button>
                    <button
                      type="button"
                      onClick={() => openRichComposer("document")}
                      className="rounded-full border border-ink/[0.08] px-2.5 py-1 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:text-fog/60"
                    >
                      📎 Send document
                    </button>
                    <button
                      type="button"
                      onClick={() => openRichComposer("sticker")}
                      className="rounded-full border border-ink/[0.08] px-2.5 py-1 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:text-fog/60"
                    >
                      🩷 Send sticker
                    </button>
                  </div>
                )}
                {target.is_unknown ? (
                  <p className="text-[12px] text-ink/45 dark:text-fog/45">
                    These messages predate contact tracking, so there is no number to reply to.
                  </p>
                ) : target.can_reply === false ? (
                  <p className="text-[12px] text-ink/45 dark:text-fog/45">
                    This is a public {target.platform === "google_reviews" ? "Google review" : "post"} — it is
                    answered from the Reviews page, not from here.
                  </p>
                ) : (
                  <>
                    {(!replyWindowOpen(target) || windowClosed) && (
                      <div className="mb-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2.5 dark:border-amber-500/30 dark:bg-amber-500/10">
                        <p className="text-[12px] font-medium text-amber-800 dark:text-amber-300">
                          Reply window closed — Meta only allows free-form replies within 24 hours of the customer&apos;s last message.
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => void openTemplatePicker(target)}
                            className="rounded-full bg-deep-violet px-3 py-1 text-[11px] font-bold text-white transition active:translate-y-[1px] active:scale-[0.98]"
                          >
                            {templateOpen ? "Hide templates" : "Send a template"}
                          </button>
                          {threadState?.opt_in_at ? (
                            <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-ink/40 dark:text-amber-200">
                              Opt-in on record
                              {threadState.opt_in_source
                                ? ` · ${threadState.opt_in_source.replace(/_/g, " ")}`
                                : ""}
                            </span>
                          ) : (
                            <>
                              <span className="text-[11px] font-medium text-amber-800/80 dark:text-amber-300/80">
                                No opt-in on record — templates need one.
                              </span>
                              <button
                                type="button"
                                onClick={() => void handleRecordConsent(target)}
                                className="rounded-full border border-amber-400/60 px-2.5 py-0.5 text-[10px] font-bold text-amber-800 transition hover:bg-amber-100 dark:border-amber-400/40 dark:text-amber-200"
                              >
                                Record consent
                              </button>
                            </>
                          )}
                        </div>

                        {templateOpen && (
                          <div className="mt-3 rounded-xl bg-white/80 p-3 dark:bg-ink/40">
                            {templateError && (
                              <p className="mb-2 text-[11px] font-medium text-[#C4304B] dark:text-[#FF8FA3]">
                                {templateError}
                              </p>
                            )}
                            {templates === null ? (
                              <p className="text-[11px] text-ink/45 dark:text-fog/45">
                                Loading templates…
                              </p>
                            ) : approvedTemplates.length === 0 ? (
                              <p className="text-[11px] text-ink/45 dark:text-fog/45">
                                No approved utility template yet. Create one in
                                WhatsApp Manager, then sync on the Templates page.
                              </p>
                            ) : (
                              <>
                                <div className="flex flex-wrap gap-1.5">
                                  {approvedTemplates.map((t) => (
                                    <button
                                      key={t.id}
                                      type="button"
                                      onClick={() => chooseTemplate(t)}
                                      aria-pressed={templateId === t.id}
                                      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition ${
                                        templateId === t.id
                                          ? "bg-deep-violet text-white"
                                          : "border border-ink/[0.1] text-ink/60 hover:border-deep-violet/40 dark:border-fog/[0.15] dark:text-fog/60"
                                      }`}
                                    >
                                      {t.name}
                                      <span className="ml-1 font-normal opacity-60">
                                        {t.language}
                                      </span>
                                    </button>
                                  ))}
                                </div>
                                {selectedTemplate && selectedTemplate.variables > 0 && (
                                  <div className="mt-2 grid gap-1.5">
                                    {templateVars.map((value, index) => (
                                      <input
                                        key={index}
                                        value={value}
                                        onChange={(e) => {
                                          const next = [...templateVars];
                                          next[index] = e.target.value;
                                          setTemplateVars(next);
                                        }}
                                        placeholder={`Variable ${index + 1}`}
                                        aria-label={`Template variable ${index + 1}`}
                                        className="input-field"
                                      />
                                    ))}
                                  </div>
                                )}
                                {selectedTemplate && (
                                  <p className="mt-2 whitespace-pre-line text-[11px] leading-4 text-ink/50 dark:text-fog/50">
                                    {selectedTemplate.body}
                                  </p>
                                )}
                                <div className="mt-2 flex justify-end">
                                  <button
                                    type="button"
                                    onClick={() => void handleSendTemplate(target)}
                                    disabled={!selectedTemplate || templateBusy}
                                    className="rounded-full bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white transition disabled:opacity-40 active:translate-y-[1px] active:scale-[0.98]"
                                  >
                                    {templateBusy ? "Sending…" : "Send template"}
                                  </button>
                                </div>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                    <div className="flex items-end gap-2">
                      <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            void send();
                          }
                        }}
                        rows={2}
                        placeholder={
                          !replyWindowOpen(target) || windowClosed
                            ? "Reply window closed"
                            : "Write a reply…"
                        }
                        aria-label="Write a reply"
                        disabled={!replyWindowOpen(target) || windowClosed}
                        className="input-field flex-1 resize-none disabled:opacity-50"
                      />
                      <button onClick={() => void send()} disabled={!canSend} className="btn-primary disabled:opacity-40">
                        {sending ? "Sending…" : "Send"}
                      </button>
                    </div>
                    <p className="mt-1.5 text-[11px] text-ink/35 dark:text-fog/35">
                      {replyWindowOpen(target) && !windowClosed
                        ? `Reply window open — closes ${replyWindowExpiresAt(target)?.toLocaleString() ?? ""}.`
                        : "WhatsApp/Instagram only allow replies within 24 hours of the customer’s last message."}
                    </p>
                  </>
                )}
              </div>
            </>
          )}
        </div>

        {/* Contact info sidebar */}
        <aside className={`${showInfo ? "flex" : "hidden"} absolute inset-0 z-20 min-h-0 flex-col overflow-y-auto rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink lg:static lg:z-auto`}>
          <div className="mb-3 flex items-center justify-between lg:hidden">
            <button
              type="button"
              onClick={() => setShowInfo(false)}
              aria-label="Back to conversation"
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[13px] font-semibold text-deep-violet"
            >
              ← Back to chat
            </button>
            <p className="text-[13px] font-bold text-ink dark:text-fog">Contact profile</p>
            <span className="w-12" aria-hidden />
          </div>
          {!target ? (
            <p className="text-[12px] text-ink/40">Select a conversation to see contact details.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-col items-center text-center">
                <button
                  type="button"
                  onClick={() => {
                    if (target.avatar_url) setPhotoOpen(true);
                  }}
                  disabled={!target.avatar_url}
                  aria-label={
                    target.avatar_url
                      ? `View ${target.display_name || "contact"} profile picture`
                      : undefined
                  }
                  className={`rounded-2xl outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                    target.avatar_url
                      ? "cursor-zoom-in hover:opacity-90"
                      : "cursor-default"
                  }`}
                >
                  <Avatar
                    name={target.display_name}
                    phone={target.contact_phone}
                    url={target.avatar_url}
                    boxCls="h-14 w-14 rounded-2xl bg-deep-violet/10 text-[16px] text-deep-violet ring-1 ring-deep-violet/10"
                  >
                    <PlatformBadge platform={target.platform} />
                  </Avatar>
                </button>
                <p className="mt-2 text-[14px] font-semibold text-ink dark:text-fog">
                  {target.display_name || "Unknown sender"}
                </p>
                {target.username && (
                  <p className="text-[12px] font-medium text-deep-violet">@{target.username}</p>
                )}
                <p className="text-[12px] text-ink/45 dark:text-fog/45">
                  {target.platform === "google_reviews" || target.platform === "google"
                    ? target.channel_name ?? "Google review"
                    : target.platform === "instagram"
                      ? target.contact_phone
                      : formatPhone(target.contact_phone)}
                </p>
              </div>
              {!target.is_unknown && (
                <label className="block md:hidden">
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                    Owner
                  </span>
                  <select
                    value={currentAssignee ?? ""}
                    onChange={(e) =>
                      void handleAssignee(target, e.target.value || null)
                    }
                    disabled={assigneeBusy}
                    aria-label="Conversation owner"
                    className="h-9 w-full rounded-lg border border-ink/[0.08] bg-white px-2 text-[12px] font-semibold text-ink disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  >
                    <option value="">Unassigned</option>
                    {assigneeNotInList && currentAssignee && (
                      <option value={currentAssignee}>
                        {currentAssigneeName ?? "Assigned"}
                      </option>
                    )}
                    {assignees.map((a) => (
                      <option key={a.user_id} value={a.user_id}>
                        {a.user_id === user?.id ? `${a.name} (you)` : a.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <dl className="space-y-2 text-[12px]">
                <div className="flex justify-between">
                  <dt className="text-ink/45 dark:text-fog/45">Platform</dt>
                  <dd className="font-semibold text-ink dark:text-fog">{platformMeta(target.platform).label}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink/45 dark:text-fog/45">Channel</dt>
                  <dd className="truncate font-semibold text-ink dark:text-fog">{target.channel_name ?? "—"}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink/45 dark:text-fog/45">Messages</dt>
                  <dd className="font-semibold text-ink dark:text-fog">{target.message_count}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink/45 dark:text-fog/45">Unread</dt>
                  <dd className="font-semibold text-ink dark:text-fog">{target.unread}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink/45 dark:text-fog/45">Last activity</dt>
                  <dd className="font-semibold text-ink dark:text-fog">{relative(target.last_message_at)}</dd>
                </div>
              </dl>
              {target.platform === "whatsapp" && (
                <div className="rounded-xl border border-ink/[0.08] p-3 dark:border-fog/[0.1]">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                    Customer access
                  </p>
                  <p className="mt-1 text-[12px] text-ink/60 dark:text-fog/60">
                    {threadState?.blocked_at
                      ? "This customer is blocked on WhatsApp."
                      : "This customer can message this number."}
                  </p>
                  <button
                    type="button"
                    disabled={blockBusy}
                    onClick={() =>
                      void handleBlockToggle(target, !threadState?.blocked_at)
                    }
                    className={`mt-2 w-full rounded-full px-3 py-1.5 text-[12px] font-bold transition disabled:opacity-50 ${
                      threadState?.blocked_at
                        ? "border border-[var(--ui-line)] text-ink/70 dark:text-fog/70"
                        : "bg-red-600 text-white"
                    }`}
                  >
                    {blockBusy
                      ? "Working…"
                      : threadState?.blocked_at
                        ? "Unblock customer"
                        : "Block customer"}
                  </button>
                  {blockError && (
                    <p role="status" className="mt-2 text-[11px] text-red-600">
                      {blockError}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>

      {photoOpen && target?.avatar_url && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Profile picture"
          className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/70 p-6"
          onClick={() => setPhotoOpen(false)}
        >
          <button
            type="button"
            onClick={() => setPhotoOpen(false)}
            aria-label="Close profile picture"
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/95 text-[20px] font-medium text-ink shadow-lg transition hover:bg-white focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            ×
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={resolveMediaUrl(target.avatar_url) || target.avatar_url}
            alt={target.display_name || "Contact profile picture"}
            className="max-h-[82vh] max-w-[82vw] rounded-2xl object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}

      {error && (
        <p role="status" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[12px] text-red-700">
          {error}
        </p>
      )}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl dark:bg-ink">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">Delete this conversation?</h2>
            <p className="mt-2 text-[12px] text-ink/60 dark:text-fog/60">
              This permanently deletes all messages in this thread. This cannot be undone.
            </p>
            {listActionError && (
              <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
                {listActionError}
              </p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                disabled={deleteBusy}
                onClick={() => setDeleteTarget(null)}
                className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteBusy}
                onClick={() => void handleDelete(deleteTarget)}
                className="rounded-[2px] bg-red-600 px-3 py-1.5 text-[12px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {deleteBusy ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
      {richComposer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl dark:bg-ink">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">
              {richComposer === "location"
                ? "Send a location"
                : richComposer === "contact"
                  ? "Send a contact card"
                  : richComposer === "document"
                    ? "Send a document"
                    : "Send a sticker"}
            </h2>
            <p className="mt-1 text-[12px] text-ink/55 dark:text-fog/55">
              {richComposer === "location"
                ? "The customer gets a native map card, not a link."
                : richComposer === "contact"
                  ? "The customer gets a native contact card they can save."
                  : richComposer === "document"
                    ? "The customer gets the file as a native WhatsApp document."
                    : "WebP only, under 500 KB — WhatsApp's sticker format."}
            </p>

            {richComposer === "location" ? (
              <div className="mt-3 space-y-2">
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Google Maps link (optional — fills the coordinates)
                  <input
                    value={locMaps}
                    onChange={(e) => {
                      const value = e.target.value;
                      setLocMaps(value);
                      const coords = coordsFromMapsLink(value);
                      if (coords) {
                        setLocLat(String(coords.lat));
                        setLocLng(String(coords.lng));
                      }
                    }}
                    placeholder="https://maps.google.com/.../@24.7136,46.6753,17z"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Place name
                  <input
                    value={locName}
                    onChange={(e) => setLocName(e.target.value)}
                    placeholder="Aster Coffee — Olaya"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Address
                  <input
                    value={locAddress}
                    onChange={(e) => setLocAddress(e.target.value)}
                    placeholder="Olaya St, Riyadh"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                    Latitude
                    <input
                      value={locLat}
                      onChange={(e) => setLocLat(e.target.value)}
                      inputMode="decimal"
                      placeholder="24.7136"
                      className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] tabular-nums text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                    />
                  </label>
                  <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                    Longitude
                    <input
                      value={locLng}
                      onChange={(e) => setLocLng(e.target.value)}
                      inputMode="decimal"
                      placeholder="46.6753"
                      className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] tabular-nums text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                    />
                  </label>
                </div>
              </div>
            ) : richComposer === "contact" ? (
              <div className="mt-3 space-y-2">
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Name
                  <input
                    value={cardName}
                    onChange={(e) => setCardName(e.target.value)}
                    placeholder="Aster Coffee"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Phone
                  <input
                    value={cardPhone}
                    onChange={(e) => setCardPhone(e.target.value)}
                    placeholder="+966 50 000 0000"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Email (optional)
                  <input
                    value={cardEmail}
                    onChange={(e) => setCardEmail(e.target.value)}
                    type="email"
                    placeholder="hello@example.com"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
              </div>
            ) : richComposer === "document" ? (
              <div className="mt-3 space-y-2">
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  File (PDF, invoice, menu, spreadsheet — under 32 MB)
                  <input
                    type="file"
                    onChange={(e) => setDocFile(e.target.files?.[0] ?? null)}
                    className="mt-1 block w-full text-[12px] text-ink/70 file:mr-2 file:rounded-full file:border-0 file:bg-deep-violet/[0.08] file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-deep-violet dark:text-fog/70 dark:file:bg-fog/[0.1] dark:file:text-fog"
                  />
                </label>
                {docFile && (
                  <p className="text-[11px] text-ink/50 dark:text-fog/50">
                    {docFile.name} · {(docFile.size / (1024 * 1024)).toFixed(1)} MB
                  </p>
                )}
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Caption (optional)
                  <input
                    value={docCaption}
                    onChange={(e) => setDocCaption(e.target.value)}
                    placeholder="Your invoice for order #1234"
                    className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                  />
                </label>
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                <label className="block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                  Sticker file (.webp, 512×512, under 500 KB)
                  <input
                    type="file"
                    accept="image/webp,.webp"
                    onChange={(e) => setStickerFile(e.target.files?.[0] ?? null)}
                    className="mt-1 block w-full text-[12px] text-ink/70 file:mr-2 file:rounded-full file:border-0 file:bg-deep-violet/[0.08] file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-deep-violet dark:text-fog/70 dark:file:bg-fog/[0.1] dark:file:text-fog"
                  />
                </label>
                {stickerFile && (
                  <p className="text-[11px] text-ink/50 dark:text-fog/50">
                    {stickerFile.name} · {(stickerFile.size / 1024).toFixed(0)} KB
                  </p>
                )}
              </div>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRichComposer(null)}
                className="rounded-full border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 dark:text-fog/70"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={richBusy}
                onClick={() =>
                  void (richComposer === "location"
                    ? sendLocationCard()
                    : richComposer === "contact"
                      ? sendContactCard()
                      : richComposer === "document"
                        ? sendDocumentFile()
                        : sendStickerFile())
                }
                className="rounded-full bg-deep-violet px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-50"
              >
                {richBusy ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
