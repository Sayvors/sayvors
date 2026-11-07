"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { setChatOpen, useChatOpen } from "@/lib/chat-store";
import { safeHref } from "@/lib/safe-url";
import { streamAssistantChat } from "@/lib/api-assistant";
import { isChatChart, type ChatChart } from "@/lib/chat-charts";
import ChatChartView from "@/components/chat/ChatChart";
import FeedbackPanel from "@/components/FeedbackPanel";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  /** Short process trail (databank lookups, thinking) kept with the answer. */
  steps?: Step[];
  charts?: ChatChart[];
  /** How long the answer took, so completed steps can say "in 6s". */
  elapsedMs?: number;
}

/** One line in the process trail: a short label plus an optional detail. */
interface Step {
  id: string;
  label: string;
  detail?: string | null;
}

interface ChatSession {
  id: string;
  title: string;
  messages: ChatMsg[];
  updatedAt: number;
}

const GREETING: ChatMsg = {
  role: "assistant",
  content:
    "Hi! I'm your Sayvors assistant. Ask me anything about your reviews, ratings, or business — I answer from your live data.",
};

const SESSIONS_KEY = "sayvors.chat.sessions";
const ACTIVE_KEY = "sayvors.chat.active";
const OLD_MSGS_KEY = "sayvors.chat.messages";
const MAX_SESSIONS = 30;

function newSession(): ChatSession {
  return {
    id: typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}`,
    title: "New chat",
    messages: [GREETING],
    updatedAt: Date.now(),
  };
}

function loadSessions(): { sessions: ChatSession[]; activeId: string } {
  if (typeof window === "undefined") {
    const s = newSession();
    return { sessions: [s], activeId: s.id };
  }
  try {
    // One-time migration from the single-history format.
    const legacy = window.localStorage.getItem(OLD_MSGS_KEY);
    if (legacy && !window.localStorage.getItem(SESSIONS_KEY)) {
      const msgs = JSON.parse(legacy) as ChatMsg[];
      const s: ChatSession = {
        id: newSession().id,
        title: "Previous chat",
        messages: Array.isArray(msgs) && msgs.length > 0 ? msgs : [GREETING],
        updatedAt: Date.now(),
      };
      window.localStorage.removeItem(OLD_MSGS_KEY);
      window.localStorage.setItem(SESSIONS_KEY, JSON.stringify([s]));
      window.localStorage.setItem(ACTIVE_KEY, s.id);
      return { sessions: [s], activeId: s.id };
    }

    const raw = window.localStorage.getItem(SESSIONS_KEY);
    if (raw) {
      const arr = JSON.parse(raw) as ChatSession[];
      if (Array.isArray(arr) && arr.length > 0) {
        const sessions = arr
          .filter((s) => s && typeof s.id === "string" && Array.isArray(s.messages))
          .map((s) => ({
            id: s.id,
            title: typeof s.title === "string" ? s.title : "New chat",
            messages: s.messages
              .filter(
                (m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string"
              )
              .map((m) => ({
                role: m.role,
                content: m.content,
                // Keep the process trail so past answers still show how they were produced.
                steps: Array.isArray(m.steps)
                  ? m.steps
                      .filter((st) => st && typeof st.id === "string" && typeof st.label === "string")
                      .map((st) => ({ id: st.id, label: st.label, detail: st.detail ?? null }))
                  : undefined,
                charts: Array.isArray(m.charts)
                  ? m.charts.filter(isChatChart)
                  : undefined,
                elapsedMs:
                  typeof m.elapsedMs === "number" ? m.elapsedMs : undefined,
              })),
            updatedAt: typeof s.updatedAt === "number" ? s.updatedAt : 0,
          }));
        if (sessions.length > 0) {
          sessions.sort((a, b) => b.updatedAt - a.updatedAt);
          const stored = window.localStorage.getItem(ACTIVE_KEY);
          const activeId = sessions.some((s) => s.id === stored) ? stored! : sessions[0].id;
          return { sessions, activeId };
        }
      }
    }
  } catch {
    /* corrupted storage — start fresh */
  }
  const s = newSession();
  return { sessions: [s], activeId: s.id };
}

/* ── Minimal safe markdown rendering (no raw HTML injection) ── */

const INLINE_RE = /(\[[^\]]+\]\([^)\s]+\))|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(`[^`]+`)/g;

/** Same-tab navigation for the dashboard pages the assistant recommends. */
function DashboardLink({ href, label }: { href: string; label: string }) {
  const router = useRouter();
  return (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        router.push(href);
      }}
      className="mx-0.5 inline-flex items-baseline gap-1 rounded-full bg-deep-violet/10 px-2 py-0.5 text-[11px] font-semibold text-deep-violet no-underline transition hover:bg-deep-violet/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:bg-fog/10 dark:text-fog dark:hover:bg-fog/15"
    >
      {label}
      <span aria-hidden className="text-[10px] leading-none">↗</span>
    </a>
  );
}

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-${i++}`;
    if (tok.startsWith("[")) {
      const link = /\[([^\]]+)\]\(([^)\s]+)\)/.exec(tok);
      if (link) {
        const href = safeHref(link[2]);
        if (href && href.startsWith("/")) {
          // In-app page: navigate in the same tab, styled as a chip so it
          // reads as an action rather than a reference.
          out.push(<DashboardLink key={key} href={href} label={link[1]} />);
        } else if (href) {
          out.push(
            <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
              {link[1]}
            </a>
          );
        } else {
          // Unsafe scheme: keep the label, never render the URL as a link.
          out.push(link[1]);
        }
      } else {
        out.push(tok);
      }
    } else if (tok.startsWith("**") || tok.startsWith("__")) {
      out.push(<strong key={key} className="font-bold">{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-ink/[0.08] px-1 py-0.5 text-[11px] dark:bg-fog/[0.12]">
          {tok.slice(1, -1)}
        </code>
      );
    } else {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function tableCells(line: string): string[] | null {
  const t = line.trim();
  if (!t.startsWith("|")) return null;
  return t.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

function renderMarkdown(text: string): React.ReactNode {
  const lines = text.split("\n");
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let bi = 0;

  const flushList = () => {
    if (!list) return;
    const items = list.items.map((item, idx) => (
      <li key={idx} className="leading-relaxed">{renderInline(item, `li-${bi}-${idx}`)}</li>
    ));
    blocks.push(
      list.ordered ? (
        <ol key={`b-${bi++}`} className="ml-4 list-decimal space-y-0.5">{items}</ol>
      ) : (
        <ul key={`b-${bi++}`} className="ml-4 list-disc space-y-0.5">{items}</ul>
      )
    );
    list = null;
  };

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li].trimEnd();
    const trimmed = line.trim();
    const cells = tableCells(trimmed);
    if (cells) {
      const rows = [cells];
      while (li + 1 < lines.length) {
        const nxt = tableCells(lines[li + 1].trim());
        if (!nxt) break;
        rows.push(nxt);
        li++;
      }
      const header = rows[0];
      let body = rows.slice(1);
      if (body.length > 0 && isSeparatorRow(body[0])) body = body.slice(1);
      const tkey = bi++;
      blocks.push(
        <div key={`b-${tkey}`} className="overflow-x-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr>
                {header.map((h, ci) => (
                  <th key={ci} className="border-b border-ink/15 px-2 py-1 text-left font-bold dark:border-fog/20">
                    {renderInline(h, `th-${tkey}-${ci}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, ri) => (
                <tr key={ri} className="border-b border-ink/[0.06] last:border-0 dark:border-fog/[0.08]">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-1 align-top">
                      {renderInline(cell, `td-${tkey}-${ri}-${ci}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }
    const ul = /^[-*]\s+(.+)$/.exec(trimmed);
    const ol = /^\d+[.)]\s+(.+)$/.exec(trimmed);
    if (ul) {
      if (!list || list.ordered) {
        flushList();
        list = { ordered: false, items: [] };
      }
      list.items.push(ul[1]);
      continue;
    }
    if (ol) {
      if (!list || !list.ordered) {
        flushList();
        list = { ordered: true, items: [] };
      }
      list.items.push(ol[1]);
      continue;
    }
    flushList();
    if (trimmed === "") {
      blocks.push(<div key={`b-${bi++}`} className="h-1.5" />);
      continue;
    }
    blocks.push(
      <p key={`b-${bi++}`} className="leading-relaxed">{renderInline(line, `p-${bi}`)}</p>
    );
  }
  flushList();
  return blocks;
}

/**
 * The process trail: what the assistant is doing right now (or did).
 *
 * While a reply is streaming it stays open and shows the real stages as they
 * arrive. Once the answer lands it collapses to one line ("Completed in 6s ·
 * 11 steps") so the conversation stays readable; the owner can reopen it.
 */
function StepTrail({
  steps,
  done,
  elapsedMs,
}: {
  steps: Step[];
  done: boolean;
  elapsedMs?: number | null;
}) {
  const [open, setOpen] = useState(!done);
  const running = !done;
  const active = steps[steps.length - 1];
  const seconds = elapsedMs ? Math.max(1, Math.round(elapsedMs / 1000)) : null;
  const headline = running
    ? active?.label ?? "Working"
    : seconds
      ? `Completed in ${seconds}s`
      : "Completed";

  return (
    <div className="overflow-hidden rounded-[14px] border border-ink/[0.07] bg-white shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_1px_2px_rgba(20,16,31,0.04)] dark:border-fog/[0.08] dark:bg-[#241a45]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:hover:bg-fog/[0.04]"
      >
        <span
          aria-hidden
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
            running
              ? "bg-deep-violet/10 text-deep-violet"
              : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
          }`}
        >
          {running ? (
            <span className="h-2 w-2 animate-pulse rounded-full bg-deep-violet" />
          ) : (
            <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M2 6.2 4.6 9 10 3.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </span>
        <span className="min-w-0 flex-1 truncate text-[11.5px] font-semibold text-ink/75 dark:text-fog/75">
          {headline}
        </span>
        <span className="shrink-0 text-[10px] tabular-nums text-ink/35 dark:text-fog/35">
          {running
            ? seconds
              ? `${seconds}s`
              : ""
            : `${steps.length} step${steps.length === 1 ? "" : "s"}`}
        </span>
        <svg
          aria-hidden
          viewBox="0 0 12 12"
          className={`h-3 w-3 shrink-0 text-ink/30 transition-transform dark:text-fog/30 ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <path d="M2.5 4.5 6 8l3.5-3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <ol className="space-y-0 border-t border-ink/[0.05] px-2.5 py-2 dark:border-fog/[0.06]">
          {steps.map((s, i) => {
            const isActive = running && i === steps.length - 1;
            const isLast = i === steps.length - 1;
            return (
              <li key={s.id} className="flex items-start gap-2 py-[3px]">
                <span className="relative flex w-3 shrink-0 justify-center">
                  <span
                    aria-hidden
                    className={`mt-[3px] h-1.5 w-1.5 rounded-full ${
                      isActive
                        ? "bg-deep-violet ring-2 ring-deep-violet/20"
                        : "bg-ink/20 dark:bg-fog/25"
                    }`}
                  />
                  {!isLast && (
                    <span
                      aria-hidden
                      className="absolute left-1/2 top-[9px] h-[calc(100%-3px)] w-px -translate-x-1/2 bg-ink/[0.08] dark:bg-fog/[0.1]"
                    />
                  )}
                </span>
                <span
                  className={`min-w-0 flex-1 text-[11px] leading-[1.45] ${
                    isActive
                      ? "font-semibold text-ink dark:text-fog"
                      : "text-ink/55 dark:text-fog/55"
                  }`}
                >
                  {s.label}
                </span>
                {s.detail && (
                  <span className="max-w-[45%] shrink-0 truncate text-right text-[10px] text-ink/35 dark:text-fog/35">
                    {s.detail}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/**
 * Ask Sayvors — secondary sidebar that sits inside the dashboard flex row
 * and pushes page content (overlays full-width on mobile). Chat history is
 * session-based and persisted in localStorage.
 */
export default function SayvorsChat() {
  const open = useChatOpen();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** In-flight answer: the process trail plus the text typed so far. */
  const [live, setLive] = useState<{ steps: Step[]; text: string; charts: ChatChart[] } | null>(null);
  const [liveStartedAt, setLiveStartedAt] = useState<number | null>(null);
  const [liveElapsedMs, setLiveElapsedMs] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Restore persisted sessions once on mount. Runs after hydration on
  // purpose: the server renders the greeting, so loading history in a lazy
  // useState initializer would mismatch the SSR markup.
  useEffect(() => {
    const { sessions: s, activeId: a } = loadSessions();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate stored history after mount
    setSessions(s);
    setActiveId(a);
    setLoaded(true);
  }, []);

  // Persist sessions (capped) after the initial load.
  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
      window.localStorage.setItem(ACTIVE_KEY, activeId);
    } catch {
      /* private mode */
    }
  }, [sessions, activeId, loaded]);

  const active = sessions.find((s) => s.id === activeId) ?? null;
  const messages = useMemo(() => active?.messages ?? [], [active]);

  useEffect(() => {
    if (open) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
      if (!busy) setTimeout(() => inputRef.current?.focus(), 240);
    }
  }, [open, messages, busy, live]);

  // Refresh the elapsed-time label while an answer is streaming.
  useEffect(() => {
    if (!busy || liveStartedAt === null) return;
    const tick = () => setLiveElapsedMs(Date.now() - liveStartedAt);
    tick();
    const id = window.setInterval(tick, 500);
    return () => window.clearInterval(id);
  }, [busy, liveStartedAt]);

  function patchActive(fn: (s: ChatSession) => ChatSession) {
    setSessions((prev) => prev.map((s) => (s.id === activeId ? fn(s) : s)));
  }

  function startNewChat() {
    abortRef.current?.abort();
    const s = newSession();
    setSessions((prev) => [s, ...prev].slice(0, MAX_SESSIONS));
    setActiveId(s.id);
    setError(null);
    setInput("");
    setLive(null);
    setLiveStartedAt(null);
    setHistoryOpen(false);
    setTimeout(() => inputRef.current?.focus(), 100);
  }

  function openSession(id: string) {
    if (id !== activeId) {
      abortRef.current?.abort();
      setLive(null);
      setLiveStartedAt(null);
    }
    setActiveId(id);
    setError(null);
    setHistoryOpen(false);
  }

  function deleteSession(id: string) {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      if (next.length === 0) {
        const s = newSession();
        setActiveId(s.id);
        return [s];
      }
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  async function send() {
    const text = input.trim();
    if (!text || busy || !active) return;
    const history = messages
      .filter((m) => m !== GREETING)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.content }));
    patchActive((s) => ({
      ...s,
      title: s.messages.filter((m) => m.role === "user").length === 0 ? text.slice(0, 48) : s.title,
      messages: [...s.messages, { role: "user", content: text }],
      updatedAt: Date.now(),
    }));
    setInput("");
    setBusy(true);
    setError(null);
    const startedAt = Date.now();
    setLiveStartedAt(startedAt);
    setLiveElapsedMs(0);
    // Empty — steps render only as the backend reports each real stage.
    // No hard-coded outline: the trail fills in live via SSE.
    setLive({ steps: [], text: "", charts: [] });

    const controller = new AbortController();
    abortRef.current = controller;
    const steps: Step[] = [];
    const charts: ChatChart[] = [];
    let answer = "";

    const addStep = (label: string, detail?: string | null, id?: string) => {
      const stepId = id ?? label;
      const existing = steps.find((s) => s.id === stepId);
      if (existing) {
        existing.label = label;
        if (detail) existing.detail = detail;
      } else {
        steps.push({ id: stepId, label, detail: detail ?? null });
      }
      setLive({
        steps: steps.map((s) => ({ ...s })),
        text: answer,
        charts: [...charts],
      });
    };

    const addChart = (chart: ChatChart) => {
      if (charts.some((c) => c.id === chart.id)) return;
      charts.push(chart);
      setLive({
        steps: steps.map((s) => ({ ...s })),
        text: answer,
        charts: [...charts],
      });
    };

    try {
      for await (const ev of streamAssistantChat(text, history, active.id, controller.signal)) {
        if (ev.type === "step" && ev.label) {
          addStep(ev.label, ev.detail, ev.id);
        } else if (ev.type === "delta" && ev.text) {
          answer += ev.text;
          setLive({
            steps: steps.map((s) => ({ ...s })),
            text: answer,
            charts: [...charts],
          });
        } else if (ev.type === "chart" && ev.chart && isChatChart(ev.chart)) {
          addChart(ev.chart);
        } else if (ev.type === "done" && Array.isArray(ev.charts)) {
          ev.charts.filter(isChatChart).forEach(addChart);
        } else if (ev.type === "error") {
          throw new Error(ev.message || "Assistant is unavailable right now.");
        }
      }
      if (!answer.trim()) throw new Error("The assistant returned an empty reply.");
      const elapsedMs = Date.now() - startedAt;
      patchActive((s) => ({
        ...s,
        messages: [
          ...s.messages,
          {
            role: "assistant",
            content: answer,
            steps,
            charts: charts.length > 0 ? charts : undefined,
            elapsedMs,
          },
        ],
        updatedAt: Date.now(),
      }));
      setLive(null);
    } catch (e) {
      if ((e as Error)?.name === "AbortError") {
        // User switched chat or started a new one — drop the partial answer.
        setLive(null);
      } else {
        let msg = "I couldn't reach the assistant. Try again.";
        const rawMsg = e instanceof Error ? e.message : "";
        const isNetwork =
          (e instanceof TypeError && /fetch|network/i.test(rawMsg)) ||
          /failed to fetch|network error|load failed/i.test(rawMsg);
        if (isNetwork) {
          msg =
            "The connection dropped before the answer finished. " +
            "Try again in a moment.";
        } else if (e instanceof Error) {
          try {
            const parsed = JSON.parse(e.message) as { detail?: unknown; message?: unknown };
            if (typeof parsed.detail === "string") msg = parsed.detail;
            else if (typeof parsed.message === "string") msg = parsed.message;
          } catch {
            const raw = e.message;
            if (raw && !raw.startsWith("{")) msg = raw.slice(0, 200);
          }
        }
        setError(msg);
        if (answer.trim() || charts.length > 0) {
          patchActive((s) => ({
            ...s,
            messages: [
              ...s.messages,
              {
                role: "assistant",
                content:
                  answer.trim() ||
                  "Here are your charts. I couldn't finish the written summary — ask again and I'll add it.",
                steps,
                charts: charts.length > 0 ? charts : undefined,
                elapsedMs: Date.now() - startedAt,
              },
            ],
            updatedAt: Date.now(),
          }));
        }
        setLive(null);
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  const filteredSessions = useMemo(() => {
    const q = search.trim().toLowerCase();
    const sorted = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt);
    if (!q) return sorted;
    return sorted.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.messages.some((m) => m.content.toLowerCase().includes(q))
    );
  }, [sessions, search]);

  return (
    <>
      {/* Scrim — mobile only; on desktop the sidebar sits in the flex row */}
      <button
        onClick={() => setChatOpen(false)}
        aria-label="Close chat"
        tabIndex={-1}
        className={`fixed inset-0 z-[75] bg-black/40 backdrop-blur-[2px] transition-opacity duration-200 md:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <aside
        aria-hidden={!open}
        aria-label="Chat with Sayvors"
        className={`relative flex h-full max-md:fixed max-md:inset-y-0 max-md:right-0 max-md:z-[80] max-md:w-full max-md:max-w-[400px] max-md:shadow-[0_0_50px_rgba(58,39,120,0.18)] md:shrink-0 md:overflow-hidden md:transition-[width] md:duration-200 md:ease-out ${
          open
            ? "max-md:translate-x-0 md:w-[400px] md:border-s md:border-ink/[0.06] md:dark:border-fog/[0.08]"
            : "max-md:translate-x-full md:w-0"
        } bg-white dark:bg-ink`}
      >
        {/* Inner column keeps its width so content never reflows mid-animation */}
        <div className="flex h-full w-full min-w-0 flex-col md:w-[400px]">
          {/* Header */}
          <div className="flex items-center gap-2.5 border-b border-ink/[0.06] bg-deep-violet px-4 py-3 dark:border-fog/[0.06]">
            <Image src="/Sayvors_Icon.png" alt="" width={28} height={28} className="h-7 w-7 rounded-[2px]" />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-bold text-white">Ask Sayvors</p>
              <p className="truncate text-[10px] text-white/60">{active?.title ?? "Answers from your live business data"}</p>
            </div>
            <button
              onClick={() => {
                setFeedbackOpen(true);
                setHistoryOpen(false);
              }}
              aria-expanded={feedbackOpen}
              aria-label="Give feedback"
              title="Feedback"
              className="rounded-[2px] p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
                <path d="M12 3.5l2.2 5.8L20 11l-5.8 1.7L12 18.5l-2.2-5.8L4 11l5.8-1.7L12 3.5Z" />
                <path d="M18.5 4.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z" strokeWidth="1.2" />
              </svg>
            </button>
            <button
              onClick={() => {
                setHistoryOpen((o) => !o);
                setFeedbackOpen(false);
              }}
              aria-expanded={historyOpen}
              aria-label="Chat history"
              title="Chat history"
              className="rounded-[2px] p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4" aria-hidden>
                <path d="M10 4a6 6 0 106 6 6 6 0 00-6-6z" />
                <path d="M10 6.5V10l2.5 1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <button
              onClick={() => setChatOpen(false)}
              aria-label="Close chat"
              className="rounded-[2px] p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
                <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="relative flex-1 space-y-2.5 overflow-y-auto px-3.5 py-3.5">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                {m.role === "user" ? (
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-[2px] bg-deep-violet px-3.5 py-2 text-[12.5px] leading-relaxed text-white">
                    {m.content}
                  </p>
                ) : (
                  <div className="w-full space-y-1.5">
                    {m.steps && m.steps.length > 0 && (
                      <StepTrail steps={m.steps} done elapsedMs={m.elapsedMs} />
                    )}
                    <div className="max-w-[88%] space-y-1 rounded-[2px] bg-ink/[0.05] px-3.5 py-2 text-[12.5px] text-ink dark:bg-fog/[0.08] dark:text-fog">
                      {renderMarkdown(m.content)}
                    </div>
                    {m.charts && m.charts.length > 0 && (
                      <div className="space-y-2">
                        {m.charts.map((chart) => (
                          <ChatChartView key={chart.id} chart={chart} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {/* In-flight: process trail, then the answer typed out */}
            {live && (
              <div className="flex justify-start">
                <div className="w-full space-y-1.5">
                  {live.steps.length > 0 && (
                    <StepTrail steps={live.steps} done={false} elapsedMs={liveElapsedMs} />
                  )}
                  {live.text ? (
                    <div className="max-w-[88%] space-y-1 rounded-[2px] bg-ink/[0.05] px-3.5 py-2 text-[12.5px] text-ink dark:bg-fog/[0.08] dark:text-fog">
                      {renderMarkdown(live.text)}
                      <span className="ml-0.5 inline-block h-3 w-[2px] translate-y-[2px] animate-pulse rounded-full bg-deep-violet align-middle" aria-hidden />
                    </div>
                  ) : live.steps.length === 0 ? (
                    <p className="flex items-center gap-1.5 rounded-[2px] bg-ink/[0.05] px-3.5 py-2.5 dark:bg-fog/[0.08]">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/40 [animation-delay:0ms] dark:bg-fog/40" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/40 [animation-delay:120ms] dark:bg-fog/40" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/40 [animation-delay:240ms] dark:bg-fog/40" />
                    </p>
                  ) : null}
                  {live.charts.length > 0 && (
                    <div className="space-y-2">
                      {live.charts.map((chart) => (
                        <ChatChartView key={chart.id} chart={chart} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {error && (
              <p className="rounded-[2px] bg-coral/10 px-3 py-2 text-[11px] font-medium text-coral">{error}</p>
            )}
          </div>

          {/* Input */}
          <div className="flex items-center gap-2 border-t border-ink/[0.06] px-3 py-2.5 dark:border-fog/[0.06]">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder="Ask about your business…"
              maxLength={2000}
              disabled={busy}
              aria-label="Message"
              className="min-w-0 flex-1 rounded-[2px] border border-ink/[0.08] bg-white px-3 py-2 text-[12.5px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/[0.1] disabled:opacity-50 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            />
            <button
              onClick={() => void send()}
              disabled={busy || !input.trim()}
              aria-label="Send message"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[2px] bg-deep-violet text-white shadow-sm shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-95 disabled:opacity-40"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4" aria-hidden>
                <path d="M10 16V4m0 0L4.5 9.5M10 4l5.5 5.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>

        {/* Feedback panel — slides over the chat inside the sidebar */}
        <div
          aria-hidden={!feedbackOpen}
          className={`absolute inset-0 z-20 transition-transform duration-200 ease-out ${
            feedbackOpen ? "translate-x-0" : "pointer-events-none translate-x-full"
          }`}
        >
          {feedbackOpen && <FeedbackPanel onClose={() => setFeedbackOpen(false)} />}
        </div>

        {/* History panel — slides over the chat inside the sidebar */}
        <div
          aria-hidden={!historyOpen}
          className={`absolute inset-0 z-20 flex flex-col bg-white transition-transform duration-200 ease-out dark:bg-ink ${
            historyOpen ? "translate-x-0" : "pointer-events-none translate-x-full"
          }`}
        >
          <div className="flex items-center gap-2.5 border-b border-ink/[0.06] bg-deep-violet px-4 py-3 dark:border-fog/[0.06]">
            <p className="flex-1 text-[13px] font-bold text-white">Chat history</p>
            <button
              onClick={() => setHistoryOpen(false)}
              aria-label="Close history"
              className="rounded-[2px] p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
                <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          <div className="space-y-2 border-b border-ink/[0.06] p-3 dark:border-fog/[0.06]">
            <button
              onClick={startNewChat}
                              className="flex w-full items-center justify-center gap-1.5 rounded-[2px] bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.99]"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
                <path d="M8 3v10M3 8h10" strokeLinecap="round" />
              </svg>
              New chat
            </button>
            <div className="relative">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/25 dark:text-fog/25" aria-hidden>
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" strokeLinecap="round" />
              </svg>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search chats…"
                aria-label="Search chats"
                className="w-full rounded-[2px] border border-ink/[0.08] bg-ink/[0.02] py-1.5 pl-8 pr-3 text-[12px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-fog/[0.1] dark:bg-fog/[0.04] dark:text-fog"
              />
            </div>
          </div>

          <div className="flex-1 space-y-1 overflow-y-auto p-2">
            {filteredSessions.length === 0 && (
              <p className="px-2 py-6 text-center text-[11px] text-ink/40 dark:text-fog/40">
                {search.trim() ? "No chats match your search." : "No chats yet."}
              </p>
            )}
            {filteredSessions.map((s) => (
              <div
                key={s.id}
                className={`group flex items-center gap-2 rounded-[2px] px-2.5 py-2 transition ${
                  s.id === activeId
                    ? "bg-deep-violet/[0.08] ring-1 ring-deep-violet/20"
                    : "hover:bg-ink/[0.03] dark:hover:bg-fog/[0.05]"
                }`}
              >
                <button
                  onClick={() => openSession(s.id)}
                  className="min-w-0 flex-1 text-start outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                >
                  <p className={`truncate text-[12px] font-semibold ${s.id === activeId ? "text-deep-violet" : "text-ink dark:text-fog"}`}>
                    {s.title}
                  </p>
                  <p className="truncate text-[10px] text-ink/40 dark:text-fog/40">
                    {s.messages.filter((m) => m.role === "user").length} message(s) ·{" "}
                    {s.updatedAt ? new Date(s.updatedAt).toLocaleDateString([], { month: "short", day: "numeric" }) : "—"}
                  </p>
                </button>
                <button
                  onClick={() => deleteSession(s.id)}
                  aria-label={`Delete chat: ${s.title}`}
                  title="Delete chat"
                  className="shrink-0 rounded-[2px] p-1.5 text-ink/25 outline-none transition hover:bg-coral/10 hover:text-coral focus-visible:ring-2 focus-visible:ring-coral/40 dark:text-fog/25"
                >
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-3.5 w-3.5" aria-hidden>
                    <path d="M4 6h12M8 6V4.5A.5.5 0 018.5 4h3a.5.5 0 01.5.5V6m2 0v9a1 1 0 01-1 1H7a1 1 0 01-1-1V6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </>
  );
}
