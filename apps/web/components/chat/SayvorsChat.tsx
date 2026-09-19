"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

const GREETING: ChatMsg = {
  role: "assistant",
  content:
    "Hi! I'm your Sayvors assistant. Ask me anything about your reviews, ratings, or business — I answer from your live data.",
};

const SIZE_KEY = "sayvors.chat.size";
const DEFAULT_SIZE = { w: 360, h: 480 };
const MIN_SIZE = { w: 300, h: 380 };
const MAX_SIZE = { w: 720, h: 900 };

function loadSize(): { w: number; h: number } {
  if (typeof window === "undefined") return DEFAULT_SIZE;
  try {
    const raw = window.localStorage.getItem(SIZE_KEY);
    if (raw) {
      const s = JSON.parse(raw) as { w?: unknown; h?: unknown };
      const w = Number(s?.w);
      const h = Number(s?.h);
      if (Number.isFinite(w) && Number.isFinite(h)) {
        return {
          w: Math.min(Math.max(Math.round(w), 280), MAX_SIZE.w),
          h: Math.min(Math.max(Math.round(h), 320), MAX_SIZE.h),
        };
      }
    }
  } catch {
    /* corrupted storage — fall back to default */
  }
  return DEFAULT_SIZE;
}

/* ── Minimal safe markdown rendering (no raw HTML injection) ── */

const INLINE_RE = /(\[[^\]]+\]\([^)\s]+\))|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(`[^`]+`)/g;

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
        out.push(
          <a key={key} href={link[2]} target="_blank" rel="noreferrer" className="underline underline-offset-2">
            {link[1]}
          </a>
        );
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

export default function SayvorsChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([GREETING]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState(loadSize);
  const [expanded, setExpanded] = useState(false);
  const prevSize = useRef(DEFAULT_SIZE);
  const dragRef = useRef<{ startX: number; startY: number; startW: number; startH: number; mode: "left" | "top" | "both" } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (expanded) return;
    try {
      window.localStorage.setItem(SIZE_KEY, JSON.stringify(size));
    } catch {
      /* private mode */
    }
  }, [size, expanded]);

  useEffect(() => {
    const clamp = () =>
      setSize((s) => ({
        w: Math.min(Math.max(s.w, MIN_SIZE.w), Math.min(MAX_SIZE.w, window.innerWidth - 40)),
        h: Math.min(Math.max(s.h, MIN_SIZE.h), Math.min(MAX_SIZE.h, window.innerHeight - 140)),
      }));
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, []);

  function toggleExpand() {
    if (expanded) {
      setSize(prevSize.current);
      setExpanded(false);
    } else {
      prevSize.current = size;
      setExpanded(true);
      setSize({
        w: Math.min(600, window.innerWidth - 40),
        h: Math.min(720, window.innerHeight - 140),
      });
    }
  }

  function onEdgeDown(e: React.MouseEvent, mode: "left" | "top" | "both") {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startY: e.clientY, startW: size.w, startH: size.h, mode };
    const onMove = (ev: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const maxW = Math.min(MAX_SIZE.w, window.innerWidth - 40);
      const maxH = Math.min(MAX_SIZE.h, window.innerHeight - 140);
      setSize({
        w: d.mode === "top" ? d.startW : Math.round(Math.min(Math.max(d.startW + (d.startX - ev.clientX), MIN_SIZE.w), maxW)),
        h: d.mode === "left" ? d.startH : Math.round(Math.min(Math.max(d.startH + (d.startY - ev.clientY), MIN_SIZE.h), maxH)),
      });
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      dragRef.current = null;
      setExpanded(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  useEffect(() => {
    if (open) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
      setTimeout(() => inputRef.current?.focus(), 240);
    }
  }, [open, messages, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const history = messages
      .filter((m) => m !== GREETING)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch("/api/v1/assistant/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, history }),
      });
      setMessages((prev) => [...prev, { role: "assistant", content: r.reply }]);
    } catch (e) {
      let msg = "I couldn't reach the assistant. Try again.";
      if (e instanceof Error) {
        try {
          const parsed = JSON.parse(e.message) as { detail?: unknown };
          if (typeof parsed.detail === "string") msg = parsed.detail;
        } catch {
          /* not JSON */
        }
      }
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[70] flex flex-col items-end gap-3">
      {/* Chat panel */}
      <div
        aria-hidden={!open}
        style={{ width: size.w, height: size.h }}
        className={`relative flex max-h-[calc(100dvh-7rem)] max-w-[calc(100vw-2.5rem)] origin-bottom-right flex-col overflow-hidden rounded-3xl border-2 border-white bg-white/95 shadow-[0_18px_50px_rgba(58,39,120,0.22)] backdrop-blur-md transition-all duration-200 ease-out dark:border-fog/[0.08] dark:bg-ink/95 ${
          open
            ? "pointer-events-auto translate-y-0 scale-100 opacity-100"
            : "pointer-events-none translate-y-4 scale-90 opacity-0"
        }`}
        role="dialog"
        aria-label="Chat with Sayvors"
      >
        {/* Resize handles (left edge, top edge, top-left corner) */}
        <div onMouseDown={(e) => onEdgeDown(e, "left")} title="Drag to resize" aria-hidden className="absolute bottom-3 left-0 top-3 z-10 w-2 cursor-ew-resize touch-none" />
        <div onMouseDown={(e) => onEdgeDown(e, "top")} title="Drag to resize" aria-hidden className="absolute left-3 right-3 top-0 z-10 h-2 cursor-ns-resize touch-none" />
        <div onMouseDown={(e) => onEdgeDown(e, "both")} title="Drag to resize" aria-hidden className="absolute left-0 top-0 z-10 h-5 w-5 cursor-nwse-resize touch-none" />
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-ink/[0.06] bg-deep-violet px-4 py-3 dark:border-fog/[0.06]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/Sayvors_Icon.png" alt="" className="h-7 w-7 rounded-lg" />
          <div className="flex-1">
            <p className="text-[13px] font-bold text-white">Ask Sayvors</p>
            <p className="text-[10px] text-white/60">Answers from your live business data</p>
          </div>
          <button
            onClick={toggleExpand}
            aria-label={expanded ? "Restore chat size" : "Expand chat"}
            title={expanded ? "Restore size" : "Expand"}
            className="rounded-lg p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
          >
            {expanded ? (
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
                <path d="M8 3H5a1 1 0 00-1 1v3M12 3h3a1 1 0 011 1v3M8 17H5a1 1 0 01-1-1v-3M12 17h3a1 1 0 001-1v-3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
                <path d="M12 3h3a1 1 0 011 1v3M8 3H5a1 1 0 00-1 1v3M12 17h3a1 1 0 001-1v-3M8 17H5a1 1 0 01-1-1v-3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>
          <button
            onClick={() => setOpen(false)}
            aria-label="Close chat"
            className="rounded-lg p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
              <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 space-y-2.5 overflow-y-auto px-3.5 py-3.5">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              {m.role === "user" ? (
                <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-deep-violet px-3.5 py-2 text-[12.5px] leading-relaxed text-white">
                  {m.content}
                </p>
              ) : (
                <div className="max-w-[85%] space-y-1 rounded-2xl rounded-bl-md bg-ink/[0.05] px-3.5 py-2 text-[12.5px] text-ink dark:bg-fog/[0.08] dark:text-fog">
                  {renderMarkdown(m.content)}
                </div>
              )}
            </div>
          ))}
          {busy && (
            <div className="flex justify-start">
              <p className="flex items-center gap-1.5 rounded-2xl rounded-bl-md bg-ink/[0.05] px-3.5 py-2.5 dark:bg-fog/[0.08]">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/40 [animation-delay:0ms] dark:bg-fog/40" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/40 [animation-delay:120ms] dark:bg-fog/40" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/40 [animation-delay:240ms] dark:bg-fog/40" />
              </p>
            </div>
          )}
          {error && (
            <p className="rounded-xl bg-coral/10 px-3 py-2 text-[11px] font-medium text-coral">{error}</p>
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
            placeholder="Ask about your reviews…"
            maxLength={2000}
            disabled={busy}
            aria-label="Message"
            className="flex-1 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12.5px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/[0.1] disabled:opacity-50 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          />
          <button
            onClick={() => void send()}
            disabled={busy || !input.trim()}
            aria-label="Send message"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-deep-violet text-white shadow-sm shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-95 disabled:opacity-40"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4" aria-hidden>
              <path d="M10 16V4m0 0L4.5 9.5M10 4l5.5 5.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>

      {/* Floating button */}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={open ? "Close Sayvors chat" : "Chat with Sayvors"}
        className="group pointer-events-auto relative flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet shadow-[0_10px_28px_rgba(58,39,120,0.4)] outline-none transition duration-200 hover:scale-105 hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-95"
      >
        {open ? (
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-5 w-5 text-white" aria-hidden>
            <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
          </svg>
        ) : (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img src="/Sayvors_Icon.png" alt="" className="h-9 w-9 rounded-full transition group-hover:scale-110" />
        )}
        {!open && (
          <span
            aria-hidden
            className="absolute -right-0.5 -top-0.5 h-3.5 w-3.5 rounded-full bg-emerald-400 ring-2 ring-white dark:ring-ink"
          />
        )}
      </button>
    </div>
  );
}
