"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import {
  fetchInboxThreads,
  fetchThreadMessages,
  sendInboxMessage,
  type InboxMessage,
  type InboxThread,
} from "@/lib/api-inbox";

type Filter = "all" | "unread" | "unknown";

/** "+966500000001" / "966500000001" -> "+966 50 000 0001" for scannability. */
function formatPhone(phone: string | null): string {
  if (!phone) return "Unknown sender";
  const p = phone.startsWith("+") ? phone : `+${phone}`;
  if (p.length <= 8) return p;
  // Keep the country code readable, group the rest in threes from the right.
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
  const sameDay = d.toDateString() === today.toDateString();
  if (sameDay) return "Today";
  const yesterday = new Date(today.getTime() - 86400000);
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString("en", { month: "short", day: "numeric" });
}

export default function InboxPage() {
  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const [messages, setMessages] = useState<InboxMessage[]>([]);
  // Which thread `messages` belongs to. Loading is derived from this rather
  // than a separate boolean: while the key does not match, the panel is still
  // fetching and the previous thread's messages must not be shown against the
  // new heading.
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  const loadThreads = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      setThreads(await fetchInboxThreads(q));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load conversations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Debounced so typing does not fire a request per keystroke.
    const t = setTimeout(() => void loadThreads(search), 250);
    return () => clearTimeout(t);
  }, [search, loadThreads]);

  const selected = useMemo(
    () => threads.find((t) => t.key === selectedKey) ?? null,
    [threads, selectedKey],
  );

  // Auto-open the newest real thread so the page is never a dead list. Derived
  // during render rather than in an effect, so there is no second render pass
  // and no chance of the list flashing empty.
  const effectiveSelected = useMemo(() => {
    if (selected) return selected;
    if (threads.length === 0) return null;
    return threads.find((t) => !t.is_unknown) ?? threads[0];
  }, [selected, threads]);

  // Identify the open thread, and ignore a fetch that finished after the user
  // moved on. The `cancelled` flag alone can't do that: the effect re-runs on
  // key change, but two keys can share a channel and channel_id, so a late
  // response for the previous key would still look current.
  const requestedKey = useRef<string | null>(null);
  const target = effectiveSelected;
  const targetKey = target ? `${target.channel_id}:${target.key}` : null;

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
    // Keyed on the composite so switching contacts on the same channel reloads.
    // `target` is derived from `targetKey`, so keying on the key alone is both
    // correct and what makes this effect re-run when the contact changes.
  }, [targetKey]);

  // Keep the newest message in view as the thread grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, targetKey]);

  const visible = useMemo(() => {
    if (filter === "unread") return threads.filter((t) => t.unread > 0);
    if (filter === "unknown") return threads.filter((t) => t.is_unknown);
    return threads;
  }, [threads, filter]);

  const unreadTotal = useMemo(
    () => threads.reduce((sum, t) => sum + t.unread, 0),
    [threads],
  );

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
      // The failed row comes back from the server, so the thread shows exactly
      // what was stored rather than an optimistic bubble.
      setMessages((prev) => [...prev, result.message]);
      setThreads((prev) =>
        prev.map((t) =>
          t.key === thread.key
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
      if (!result.sent) setSendError(result.error || "WhatsApp rejected this message.");
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Could not send the message.");
    } finally {
      setSending(false);
    }
  };

  const canSend = !!target && !target.is_unknown && !!draft.trim() && !sending;

  return (
    <div className="flex h-full flex-col p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Inbox</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            Every WhatsApp conversation across your connected numbers.
          </p>
        </div>
        <button
          onClick={() => void loadThreads(search)}
          className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        >
          Refresh
        </button>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        {/* Thread list */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
          <div className="border-b border-ink/[0.06] p-3 dark:border-fog/[0.06]">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search messages"
              aria-label="Search messages"
              className="input-field w-full"
            />
            <div className="mt-2 flex gap-1">
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
                    filter === f.key
                      ? "bg-deep-violet/10 text-deep-violet"
                      : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading && threads.length === 0 ? (
              <div className="flex justify-center py-16"><LogoLoader size={28} /></div>
            ) : visible.length === 0 ? (
              <p className="px-4 py-10 text-center text-[12px] text-ink/40">
                {search
                  ? "No conversations match that search."
                  : "No messages yet. Once customers message your number they appear here."}
              </p>
            ) : (
              <ul>
                {visible.map((t) => {
                  const active = `${t.channel_id}:${t.key}` === targetKey;
                  return (
                    <li key={`${t.channel_id}:${t.key}`}>
                      <button
                        onClick={() => { setSelectedKey(t.key); setSendError(null); }}
                        aria-current={active}
                        className={`flex w-full items-start gap-3 border-b border-ink/[0.04] px-3 py-3 text-left transition dark:border-fog/[0.04] ${
                          active ? "bg-deep-violet/[0.06]" : "hover:bg-ink/[0.02] dark:hover:bg-fog/[0.03]"
                        }`}
                      >
                        <span
                          aria-hidden
                          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet"
                        >
                          {initials(t.display_name, t.contact_phone)}
                        </span>
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
                              <span
                                className="ml-auto shrink-0 rounded-full bg-deep-violet px-1.5 text-[10px] font-bold text-white"
                                aria-label={`${t.unread} unread`}
                              >
                                {t.unread}
                              </span>
                            )}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Thread detail */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
          {!target ? (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ink/40">
              Select a conversation to read it.
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 border-b border-ink/[0.06] px-4 py-3 dark:border-fog/[0.06]">
                <span
                  aria-hidden
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet"
                >
                  {initials(target.display_name, target.contact_phone)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold text-ink dark:text-fog">
                    {target.display_name || "Unknown sender"}
                  </p>
                  <p className="truncate text-[11px] text-ink/45 dark:text-fog/45">
                    {formatPhone(target.contact_phone)}
                    {target.channel_name ? ` · ${target.channel_name}` : ""}
                  </p>
                </div>
                {target.is_unknown && (
                  <span className="shrink-0 rounded-full bg-amber-100 px-2 py-1 text-[10px] font-bold text-amber-700">
                    Sender not recorded
                  </span>
                )}
              </div>

              <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                {loadedKey !== targetKey ? (
                  <div className="flex justify-center py-16"><LogoLoader size={24} /></div>
                ) : messages.length === 0 ? (
                  <p className="py-10 text-center text-[12px] text-ink/40">No messages.</p>
                ) : (
                  messages.map((m, i) => {
                    // A day divider whenever the date changes between messages.
                    const showDay =
                      i === 0 ||
                      new Date(messages[i - 1].created_at).toDateString() !==
                        new Date(m.created_at).toDateString();
                    const mine = m.direction === "outbound";
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
                              className={`mt-1 text-right text-[10px] ${
                                mine
                                  ? m.status === "failed"
                                    ? "text-red-500"
                                    : "text-white/70"
                                  : "text-ink/35 dark:text-fog/35"
                              }`}
                            >
                              {clockTime(m.created_at)}
                              {mine && m.status === "failed" ? " Â· not sent" : ""}
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
                  <p
                    role="status"
                    className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:bg-red-950/40 dark:text-red-300"
                  >
                    {sendError}
                  </p>
                )}
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
                        // Enter sends; Shift+Enter is a newline.
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          void send();
                        }
                      }}
                      rows={2}
                      placeholder="Write a replyâ€¦"
                      aria-label="Write a reply"
                      className="input-field flex-1 resize-none"
                    />
                    <button onClick={() => void send()} disabled={!canSend} className="btn-primary disabled:opacity-40">
                      {sending ? "Sendingâ€¦" : "Send"}
                    </button>
                  </div>
                )}
                <p className="mt-1.5 text-[11px] text-ink/35 dark:text-fog/35">
                  WhatsApp only allows replies within 24 hours of a customer&apos;s message. Outside
                  that window the send is rejected and shown here as failed.
                </p>
              </div>
            </>
          )}
        </div>
      </div>

      {error && (
        <p role="status" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[12px] text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
