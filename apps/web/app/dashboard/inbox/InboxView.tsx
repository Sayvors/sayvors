"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import LogoLoader from "@/components/LogoLoader";
import {
  fetchInboxThreads,
  fetchThreadMessages,
  sendInboxMessage,
  UNKNOWN_THREAD_KEY,
  type InboxMessage,
  type InboxThread,
} from "@/lib/api-inbox";
import { platformMeta } from "@/lib/platform";
import { useInboxRealtime, type InboxRealtimeEvent } from "@/lib/use-inbox-realtime";

type Filter = "all" | "unread" | "unknown";

const QUICK_REPLIES = [
  "Thanks for reaching out! How can I help?",
  "Sure, give me a moment to check that.",
  "Could you share more details?",
  "All set — anything else I can do for you?",
];

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
  return (
    <span className="relative shrink-0" aria-hidden>
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="" className={`object-cover ${boxCls}`} />
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

export default function InboxView() {
  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [pinned, setPinned] = useState<Set<string>>(() => {
    try {
      const raw = typeof window !== "undefined" ? localStorage.getItem("sayvors.inbox.pinned") : null;
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });

  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [threadQuery, setThreadQuery] = useState("");
  const [showInfo, setShowInfo] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);

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

  const togglePin = (compositeKey: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(compositeKey)) next.delete(compositeKey);
      else next.add(compositeKey);
      try {
        localStorage.setItem("sayvors.inbox.pinned", JSON.stringify([...next]));
      } catch {}
      return next;
    });
  };

  const loadThreads = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchInboxThreads(q);
      setThreads(list);
      const deep = deepLinkRef.current;
      if (deep.channel && deep.key) {
        const hit = list.find((t) => t.channel_id === deep.channel && t.key === deep.key);
        if (hit) {
          setSelectedKey(`${hit.channel_id}:${hit.key}`);
          deepLinkRef.current = { channel: null, key: null };
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load conversations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => void loadThreads(search), 250);
    return () => clearTimeout(t);
  }, [search, loadThreads]);

  const selected = useMemo(
    () => threads.find((t) => `${t.channel_id}:${t.key}` === selectedKey) ?? null,
    [threads, selectedKey],
  );

  const effectiveSelected = useMemo(() => {
    if (selected) return selected;
    if (threads.length === 0) return null;
    return threads.find((t) => !t.is_unknown) ?? threads[0];
  }, [selected, threads]);

  const requestedKey = useRef<string | null>(null);
  const target = effectiveSelected;
  const targetKey = target ? `${target.channel_id}:${target.key}` : null;
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
    if (e.type !== "message" || !e.channel_id || !e.id) return;
    const contactKey = e.contact_phone ?? UNKNOWN_THREAD_KEY;
    const composite = `${e.channel_id}:${contactKey}`;
    const open = composite === targetKeyRef.current;
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
      created_at: e.created_at ?? new Date().toISOString(),
    };
    if (open) {
      setMessages((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
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
    (async () => {
      try {
        const rows = await fetchThreadMessages(target.channel_id, target.contact_phone);
        if (!cancelled && requestedKey.current === targetKey) {
          setMessages(rows);
          setLoadedKey(targetKey);
        }
      } catch (e) {
        if (!cancelled && requestedKey.current === targetKey) {
          setMessages([]);
          setLoadedKey(targetKey);
          setError(e instanceof Error ? e.message : "Could not load this conversation.");
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, targetKey]);

  const platformsPresent = useMemo(() => {
    const set = new Set<string>();
    for (const t of threads) if (t.platform) set.add(t.platform);
    return [...set];
  }, [threads]);

  const visible = useMemo(() => {
    let rows = threads;
    if (filter === "unread") rows = rows.filter((t) => t.unread > 0);
    if (filter === "unknown") rows = rows.filter((t) => t.is_unknown);
    if (platformFilter !== "all") rows = rows.filter((t) => t.platform === platformFilter);
    return [...rows].sort((a, b) => {
      const ap = pinned.has(`${a.channel_id}:${a.key}`) ? 0 : 1;
      const bp = pinned.has(`${b.channel_id}:${b.key}`) ? 0 : 1;
      return ap - bp;
    });
  }, [threads, filter, platformFilter, pinned]);

  const unreadTotal = useMemo(() => threads.reduce((s, t) => s + t.unread, 0), [threads]);

  const threadView = useMemo(() => {
    const q = threadQuery.trim().toLowerCase();
    if (!q) return messages;
    return messages.filter((m) => m.content.toLowerCase().includes(q));
  }, [messages, threadQuery]);

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
      });
      setDraft("");
      setMessages((prev) => [...prev, result.message]);
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
      if (!result.sent)
        setSendError(
          result.error ||
            (target?.platform === "instagram"
              ? "Instagram rejected this message."
              : "WhatsApp rejected this message."),
        );
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the message.");
    } finally {
      setSending(false);
    }
  };

  const canSend = !!target && !target.is_unknown && !!draft.trim() && !sending;
  const openThread = !!target;

  return (
    <div className="flex h-full flex-col p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Inbox</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            Every conversation across your connected numbers.
          </p>
        </div>
        <button
          onClick={() => void loadThreads(search)}
          className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        >
          Refresh
        </button>
      </div>

      <div className={`relative grid min-h-0 flex-1 gap-4 ${showInfo ? "lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)_minmax(0,260px)]" : "lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]"}`}>
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
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading && threads.length === 0 ? (
              <div className="flex justify-center py-16"><LogoLoader size={28} /></div>
            ) : visible.length === 0 ? (
              <p className="px-4 py-10 text-center text-[12px] text-ink/40">
                {search ? "No conversations match that search." : "No messages yet. Once customers message your number they appear here."}
              </p>
            ) : (
              <ul>
                {visible.map((t) => {
                  const composite = `${t.channel_id}:${t.key}`;
                  const active = composite === targetKey;
                  const isPinned = pinned.has(composite);
                  return (
                    <li key={composite}>
                      <div className={`flex items-start border-b border-ink/[0.04] dark:border-fog/[0.04] ${active ? "bg-deep-violet/[0.06]" : "hover:bg-ink/[0.02] dark:hover:bg-fog/[0.03]"}`}>
                        <button
                          onClick={() => { setSelectedKey(composite); setSendError(null); }}
                          aria-current={active}
                          className="flex min-w-0 flex-1 items-start gap-3 px-3 py-3 text-left"
                        >
                          <Avatar
                            name={t.display_name}
                            phone={t.contact_phone}
                            url={t.avatar_url}
                            boxCls="h-9 w-9 rounded-xl bg-deep-violet/10 text-[11px] text-deep-violet"
                          >
                            <PlatformBadge platform={t.platform} />
                          </Avatar>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-baseline justify-between gap-2">
                              <span className="truncate text-[13px] font-semibold text-ink dark:text-fog">
                                {t.display_name || "Unknown sender"}
                              </span>
                              <span className="shrink-0 text-[11px] text-ink/35 dark:text-fog/35">
                                {relative(t.last_message_at)}
                              </span>
                            </span>
                            <span className="mt-0.5 flex items-center gap-1.5">
                              <span className="truncate text-[12px] text-ink/50 dark:text-fog/50">
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
                          onClick={() => togglePin(composite)}
                          aria-label={isPinned ? "Unpin thread" : "Pin thread"}
                          className={`px-2 py-3 text-[13px] ${isPinned ? "text-deep-violet" : "text-ink/20 hover:text-ink/50"}`}
                        >
                          📌
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
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
              <div className="flex items-center gap-3 border-b border-ink/[0.06] px-3 py-3 dark:border-fog/[0.06]">
                <button
                  onClick={() => setSelectedKey(null)}
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
                    boxCls="h-10 w-10 rounded-xl bg-deep-violet/10 text-[11px] text-deep-violet ring-1 ring-deep-violet/10"
                  >
                    <PlatformBadge platform={target.platform} />
                  </Avatar>
                  <span className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-semibold text-ink dark:text-fog">
                      {target.display_name || "Unknown sender"}
                    </p>
                    <p className="truncate text-[11px] text-ink/45 dark:text-fog/45">
                      {/* An IGSID is not a phone number — no formatting. */}
                      {target.platform === "instagram"
                        ? target.contact_phone
                        : formatPhone(target.contact_phone)}
                      {target.channel_name ? ` · ${target.channel_name}` : ""}
                    </p>
                  </span>
                </button>
                {target.is_unknown && (
                  <span className="hidden shrink-0 rounded-full bg-amber-100 px-2 py-1 text-[10px] font-bold text-amber-700 sm:inline">
                    Sender not recorded
                  </span>
                )}
              </div>

              <div className="border-b border-ink/[0.04] px-3 py-2 dark:border-fog/[0.04]">
                <input
                  value={threadQuery}
                  onChange={(e) => setThreadQuery(e.target.value)}
                  placeholder="Search in conversation…"
                  aria-label="Search in conversation"
                  className="input-field w-full"
                />
              </div>

              <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                {loadedKey !== targetKey ? (
                  <div className="flex justify-center py-16"><LogoLoader size={24} /></div>
                ) : threadView.length === 0 ? (
                  <p className="py-10 text-center text-[12px] text-ink/40">
                    {threadQuery ? "No messages match." : "No messages."}
                  </p>
                ) : (
                  threadView.map((m, i) => {
                    const showDay =
                      i === 0 ||
                      new Date(threadView[i - 1].created_at).toDateString() !== new Date(m.created_at).toDateString();
                    const mine = m.direction === "outbound";
                    if (m.content_type === "reaction") {
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
                      <div key={m.id}>
                        {showDay && (
                          <p className="my-3 text-center text-[11px] font-semibold text-ink/30 dark:text-fog/30">
                            {dayLabel(m.created_at)}
                          </p>
                        )}
                        <div className={`mb-2 flex ${mine ? "justify-end" : "justify-start"}`}>
                          <div
                            className={`max-w-[78%] rounded-2xl px-3 py-2 ${
                              mine
                                ? m.status === "failed"
                                  ? "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-200"
                                  : "bg-deep-violet text-white"
                                : "bg-ink/[0.05] text-ink dark:bg-fog/[0.08] dark:text-fog"
                            }`}
                          >
                            <p className="whitespace-pre-wrap break-words text-[13px]">{m.content}</p>
                            <p
                              className={`mt-1 flex items-center justify-end gap-1 text-[10px] ${
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
                      </div>
                    );
                  })
                )}
              </div>

              <div className="border-t border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                {sendError && (
                  <p role="status" className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:bg-red-950/40 dark:text-red-300">
                    {sendError}
                  </p>
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
                {target.is_unknown ? (
                  <p className="text-[12px] text-ink/45 dark:text-fog/45">
                    These messages predate contact tracking, so there is no number to reply to.
                  </p>
                ) : (
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
                      placeholder="Write a reply…"
                      aria-label="Write a reply"
                      className="input-field flex-1 resize-none"
                    />
                    <button onClick={() => void send()} disabled={!canSend} className="btn-primary disabled:opacity-40">
                      {sending ? "Sending…" : "Send"}
                    </button>
                  </div>
                )}
                <p className="mt-1.5 text-[11px] text-ink/35 dark:text-fog/35">
                  WhatsApp only allows replies within 24 hours of a customer&apos;s message. Outside that window the send is rejected and shown here as failed.
                </p>
              </div>
            </>
          )}
        </div>

        {/* Contact info sidebar */}
        <aside className={`${showInfo ? "flex" : "hidden"} absolute inset-0 z-20 min-h-0 flex-col overflow-y-auto rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink lg:static lg:z-auto`}>
          <div className="mb-3 flex items-center justify-between lg:hidden">
            <p className="text-[13px] font-bold text-ink dark:text-fog">Contact profile</p>
            <button onClick={() => setShowInfo(false)} aria-label="Close contact profile" className="rounded-lg px-2 py-1 text-[13px] font-semibold text-deep-violet">
              Close
            </button>
          </div>
          {!target ? (
            <p className="text-[12px] text-ink/40">Select a conversation to see contact details.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-col items-center text-center">
                <Avatar
                  name={target.display_name}
                  phone={target.contact_phone}
                  url={target.avatar_url}
                  boxCls="h-14 w-14 rounded-2xl bg-deep-violet/10 text-[16px] text-deep-violet ring-1 ring-deep-violet/10"
                >
                  <PlatformBadge platform={target.platform} />
                </Avatar>
                <p className="mt-2 text-[14px] font-semibold text-ink dark:text-fog">
                  {target.display_name || "Unknown sender"}
                </p>
                {target.username && (
                  <p className="text-[12px] font-medium text-deep-violet">@{target.username}</p>
                )}
                <p className="text-[12px] text-ink/45 dark:text-fog/45">
                  {target.platform === "instagram"
                    ? target.contact_phone
                    : formatPhone(target.contact_phone)}
                </p>
              </div>
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
            </div>
          )}
        </aside>
      </div>

      {error && (
        <p role="status" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[12px] text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
