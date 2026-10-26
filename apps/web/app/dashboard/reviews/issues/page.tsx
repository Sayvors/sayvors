"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import { fetchMetaAssets } from "@/lib/api-meta";
import {
  fetchReviewIssues,
  mintHandoffCode,
  updateReviewIssue,
  waMeLink,
  type ReviewIssue,
} from "@/lib/api-review-issues";
import { useInboxRealtime } from "@/lib/use-inbox-realtime";

/**
 * Review tickets — one row per classified Google review that opened a ticket.
 *
 * The assistant does the interviewing on WhatsApp; this page is the merchant's
 * side of the loop: what came in, what it was about, where it stands, and the
 * handoff link that reconnects a customer to their ticket. Status is the
 * merchant's to set; nothing here is automatic except the classification.
 *
 * Theme: the team page's flat --ui-* primitives (hairlines, no shadows).
 */

const UI_BTN = "ui-btn rounded-lg text-[12px] font-bold";
const BTN = `${UI_BTN} px-5 py-3`;
const BTN_PRIMARY = `${BTN} bg-[var(--ui-ink)] text-[var(--ui-on-ink)]`;
const BTN_GHOST = `${BTN} bg-[var(--ui-surface)] text-[var(--ui-ink)]`;

const STATUSES = ["new", "open", "in_progress", "resolved", "closed"] as const;
const UNRESOLVED = new Set(["new", "open", "in_progress"]);

const label = (s: string) => s.replace(/_/g, " ");

function Chip({ strong, children }: { strong?: boolean; children: React.ReactNode }) {
  // Status rides on weight, not hue — the flat theme's three-colour rule.
  return (
    <span className={`ui-chip px-3 py-1.5 text-[12px] ${strong ? "font-bold text-[var(--ui-ink)]" : "font-medium text-[var(--ui-ink-2)]"}`}>
      {children}
    </span>
  );
}

export default function ReviewTicketsPage() {
  const [issues, setIssues] = useState<ReviewIssue[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [waPhone, setWaPhone] = useState<string | null>(null);

  // `silent` keeps the list mounted during a realtime refresh: a ticket
  // appearing must not blank the page the merchant is reading.
  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setLoading(true);
    setError(null);
    try {
      // 200 is the API ceiling; like the admin queue, slice in memory.
      const d = await fetchReviewIssues({ ticketed: true, limit: 200 });
      setIssues(d.issues);
      setTotal(d.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load review tickets.");
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Live tickets. One poll loop classified a review and opened a ticket while
  // nobody was on this page — a customer complaining, then walking in on
  // WhatsApp — so the queue refetches itself on every lifecycle change.
  // Coalesced: a new ticket arrives as `created` plus `handoff_minted`, and
  // a customer returning can chain further updates; without the window that
  // is several redundant fetches for one row.
  const burst = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshQuietly = useCallback(() => {
    if (burst.current) clearTimeout(burst.current);
    burst.current = setTimeout(() => void load({ silent: true }), 400);
  }, [load]);

  useEffect(() => () => {
    if (burst.current) clearTimeout(burst.current);
  }, []);

  useInboxRealtime(useCallback((e) => {
    if (e.type === "review_issue") refreshQuietly();
  }, [refreshQuietly]));

  // The connected WhatsApp business number turns a code into a tappable
  // link. Absent (never connected) the drawer falls back to the bare code.
  useEffect(() => {
    let cancelled = false;
    fetchMetaAssets("whatsapp")
      .then((d) => {
        if (cancelled) return;
        const phone = d.assets.find((a) => a.active && a.phone)?.phone ?? null;
        setWaPhone(phone);
      })
      .catch(() => {
        if (!cancelled) setWaPhone(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stats = useMemo(
    () => ({
      unresolved: issues.filter((i) => UNRESOLVED.has(i.status)).length,
      attention: issues.filter((i) => i.needs_attention && UNRESOLVED.has(i.status)).length,
      resolved: issues.filter((i) => !UNRESOLVED.has(i.status)).length,
      urgent: issues.filter((i) => (i.priority === "urgent" || i.priority === "high") && UNRESOLVED.has(i.status)).length,
    }),
    [issues],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const priorityRank: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 };
    return issues
      .filter((i) => {
        if (statusFilter && i.status !== statusFilter) return false;
        if (!needle) return true;
        return [i.ticket_number, i.handoff_code, i.reviewer_name, i.review_text, i.summary, i.primary_category, i.subcategory, i.subcategory_detail]
          .filter(Boolean)
          .some((v) => (v as string).toLowerCase().includes(needle));
      })
      .sort((a, b) => (priorityRank[a.priority] ?? 2) - (priorityRank[b.priority] ?? 2));
  }, [issues, statusFilter, q]);

  const open = openId ? issues.find((i) => i.id === openId) ?? null : null;

  return (
    <div className="team-ui h-full overflow-y-auto px-6 py-6 pb-24">
      <div className="mx-auto max-w-5xl">
        {/* ── header ─────────────────────────────────────────── */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-bold text-[var(--ui-ink)]">Review tickets</h1>
            <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
              Problems customers reported in Google reviews that need action, and the WhatsApp handoff that lets the assistant solve them. Praise and neutral reviews are classified, but they do not get tickets and are not shown here.
            </p>
          </div>
          <button type="button" onClick={() => void load()} disabled={loading} className={BTN_GHOST}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>

        {error && (
          <p role="alert" className="mt-4 border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-3 text-[13px] font-medium text-[var(--ui-ink)]">
            {error}
          </p>
        )}

        {/* ── the queue in one line ──────────────────────────── */}
        <div className="mt-5 grid gap-3 sm:grid-cols-4">
          {(
            [
              ["Unresolved", stats.unresolved],
              ["Waiting on you", stats.attention],
              ["Urgent", stats.urgent],
              ["Resolved", stats.resolved],
            ] as [string, number][]
          ).map(([k, v]) => (
            <div
              key={k}
              className={`ui-panel px-4 py-3 ${k === "Urgent" && v > 0 ? "border-red-500" : ""}`}
            >
              <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{k}</div>
              <div className={`mt-1 text-[24px] font-bold leading-none tabular-nums ${k === "Urgent" && v > 0 ? "text-red-600" : "text-[var(--ui-ink)]"}`}>{v.toLocaleString()}</div>
            </div>
          ))}
        </div>

        {/* ── filters ────────────────────────────────────────── */}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label="Filter by status"
            className="ui-input w-auto bg-[var(--ui-surface)] px-3 py-2 text-[13px] font-semibold text-[var(--ui-ink)]"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)} ({issues.filter((i) => i.status === s).length})
              </option>
            ))}
          </select>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search ticket, code, reviewer, text"
            aria-label="Search review tickets"
            type="search"
            className="ui-input w-full max-w-72 bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] placeholder:text-[var(--ui-ink-2)]"
          />
          <span className="text-[12px] text-[var(--ui-ink-2)]">
            <span className="font-bold tabular-nums text-[var(--ui-ink)]">{filtered.length}</span> shown
          </span>
        </div>

        {/* ── the list ───────────────────────────────────────── */}
        {loading && issues.length === 0 ? (
          <div className="flex justify-center py-20">
            <LogoLoader size={30} />
          </div>
        ) : filtered.length === 0 ? (
          <div className="ui-panel mt-4 px-6 py-12 text-center">
            <p className="text-[14px] font-bold text-[var(--ui-ink)]">
              {issues.length === 0 ? "No tickets yet" : "Nothing matches"}
            </p>
            <p className="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
              {issues.length === 0
                ? `Tickets appear here when a review needs attention. ${total > 0 ? `(${total} exist but none loaded — try Refresh.)` : ""}`
                : "Try clearing the search or the status filter."}
            </p>
          </div>
        ) : (
          <div className="ui-panel mt-4 divide-y divide-[var(--ui-line)]">
            {filtered.map((i) => (
              <button
                key={i.id}
                type="button"
                onClick={() => setOpenId(i.id)}
                className={`block w-full px-4 py-3.5 text-left transition hover:bg-[var(--ui-sunken)] ${
                  i.priority === "urgent"
                    ? "border-l-4 border-red-500 bg-red-50"
                    : i.priority === "high"
                      ? "border-l-4 border-amber-500 bg-amber-50"
                      : ""
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-bold tabular-nums text-[var(--ui-ink)]">{i.ticket_number ?? "Unticketed"}</span>
                  <Chip strong={i.priority === "urgent" || i.priority === "high"}>{label(i.priority)}</Chip>
                  <Chip strong={UNRESOLVED.has(i.status)}>{label(i.status)}</Chip>
                  <span className="ml-auto text-[12px] text-[var(--ui-ink-2)]">{new Date(i.created_at).toLocaleDateString()}</span>
                </div>
                <p className="mt-1.5 truncate text-[13px] text-[var(--ui-ink)]">
                  {i.summary || i.review_text || label(i.primary_category)}
                </p>
                <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                  {label(i.primary_category)} · {label(i.subcategory)}
                  {i.handoff_code && <> · code <span className="font-semibold tabular-nums text-[var(--ui-ink)]">#{i.handoff_code}</span></>}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>

      {open && (
        <TicketDrawer
          issue={open}
          waPhone={waPhone}
          onClose={() => setOpenId(null)}
          onChanged={(row) =>
            setIssues((prev) => prev.map((x) => (x.id === row.id ? row : x)))
          }
        />
      )}
    </div>
  );
}

/* ── detail drawer ──────────────────────────────────────────────────── */

/**
 * Human label for a code's remaining life. An absolute timestamp is noise in
 * a drawer; "expires in 23h" is the decision the merchant is actually making
 * (re-mint now, or leave it).
 */
function describeExpiry(iso: string | null): string | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms)) return null;
  if (ms <= 0) return "expired";
  const minutes = Math.ceil(ms / 60_000);
  if (minutes < 60) return `expires in ${minutes} min`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 48) return `expires in ${hours}h`;
  return `expires in ${Math.ceil(hours / 24)} days`;
}

function TicketDrawer({
  issue,
  waPhone,
  onClose,
  onChanged,
}: {
  issue: ReviewIssue;
  waPhone: string | null;
  onClose: () => void;
  onChanged: (row: ReviewIssue) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(issue.handoff_code);
  const [expiresAt, setExpiresAt] = useState<string | null>(
    issue.handoff_code_expires_at,
  );
  const [copied, setCopied] = useState(false);

  const link = code ? waMeLink(waPhone, code) : "";
  const expired = !!expiresAt && new Date(expiresAt).getTime() <= Date.now();
  const expiryLabel = describeExpiry(expiresAt);

  async function setStatus(status: string) {
    setBusy(status);
    setError(null);
    try {
      onChanged(await updateReviewIssue(issue.id, { status }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the ticket.");
    } finally {
      setBusy(null);
    }
  }

  async function mint() {
    setBusy("code");
    setError(null);
    try {
      const row = await mintHandoffCode(issue.id);
      setCode(row.handoff_code);
      setExpiresAt(row.handoff_code_expires_at);
      onChanged(row);
    } catch (e) {
      // 422 = praise or neutral chatter: nothing to hand off. A fact about
      // the ticket, so it shows as a message rather than a failure.
      setError(e instanceof Error ? e.message : "Could not mint a code.");
    } finally {
      setBusy(null);
    }
  }

  async function copyLink() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard can be blocked (permissions, http); the link stays
      // selectable on screen either way.
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close ticket"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Ticket ${issue.ticket_number ?? issue.review_id}`}
        className="team-ui relative h-full w-full max-w-xl overflow-y-auto border-l border-[var(--ui-line)] bg-[var(--ui-page)] p-5"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[18px] font-bold text-[var(--ui-ink)]">{issue.ticket_number ?? "Unticketed"}</h2>
            <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
              {label(issue.primary_category)} · {label(issue.subcategory)} · found {new Date(issue.created_at).toLocaleString()}
            </p>
          </div>
          <button type="button" onClick={onClose} className={`${UI_BTN} bg-[var(--ui-surface)] px-4 py-2 text-[var(--ui-ink)]`}>
            Close
          </button>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip strong={issue.priority === "urgent" || issue.priority === "high"}>{label(issue.priority)}</Chip>
          <Chip strong={UNRESOLVED.has(issue.status)}>{label(issue.status)}</Chip>
          <Chip>{issue.sentiment}</Chip>
          <Chip>{issue.rating}★</Chip>
          {issue.needs_attention && <Chip strong>needs attention</Chip>}
        </div>

        {error && (
          <p role="alert" className="mt-3 border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-2.5 text-[13px] font-medium text-[var(--ui-ink)]">
            {error}
          </p>
        )}

        {issue.review_text && (
          <div className="ui-panel mt-4 px-4 py-3">
            <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">The review</div>
            <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-[var(--ui-ink)]">{issue.review_text}</p>
          </div>
        )}

        <div className="ui-panel mt-3 px-4 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">What the assistant understood</div>
          <dl className="mt-1.5 space-y-1.5 text-[13px]">
            {(
              [
                ["Reviewer", issue.reviewer_name ?? "not named"],
                ["Intent", label(issue.intent)],
                ["Detail", issue.subcategory_detail],
                ["Summary", issue.summary],
              ] as [string, string | null][]
            ).map(([k, v]) => (
              <div key={k} className="flex gap-3">
                <dt className="w-28 shrink-0 text-[var(--ui-ink-2)]">{k}</dt>
                <dd className="min-w-0 break-words text-[var(--ui-ink)]">{v ?? "—"}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="ui-panel mt-3 px-4 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">Set status</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {STATUSES.filter((s) => s !== issue.status).map((s) => (
              <button
                key={s}
                type="button"
                disabled={busy !== null}
                onClick={() => void setStatus(s)}
                className={`${UI_BTN} border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[var(--ui-ink)] disabled:opacity-40`}
              >
                {busy === s ? "Saving…" : label(s)}
              </button>
            ))}
          </div>
        </div>

        <div className="ui-panel mt-3 px-4 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">WhatsApp handoff</div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
            {code
              ? "The customer sends this code on WhatsApp, and the assistant picks up the ticket with the full story already in context. The # is part of the code — it is what tells the assistant this is a ticket, not an ordinary word."
              : "No code yet. Mint one to hand this ticket to the customer on WhatsApp — the assistant then knows the issue before they say a word."}
          </p>
          {code ? (
            <>
              <p className="mt-3 bg-[var(--ui-sunken)] px-4 py-3 text-center text-[18px] font-bold tabular-nums tracking-[0.2em] text-[var(--ui-ink)]">
                #{code}
              </p>
              <p className="mt-1 text-center text-[11px] text-[var(--ui-ink-2)]">
                {expiryLabel ? `Code ${expiryLabel}` : "Legacy code — no expiry"}
              </p>
              {expired ? (
                <div className="mt-2">
                  <p className="text-[12px] text-[var(--ui-ink-2)]">
                    This code has expired, so the link in the old review reply no longer attaches the ticket.
                  </p>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void mint()}
                    className={`${BTN_PRIMARY} mt-2 disabled:opacity-40`}
                  >
                    {busy === "code" ? "Minting…" : "Mint a new code"}
                  </button>
                </div>
              ) : link ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => void copyLink()} className={BTN_PRIMARY}>
                    {copied ? "Copied" : "Copy WhatsApp link"}
                  </button>
                  <a href={link} target="_blank" rel="noreferrer" className="text-[12px] font-semibold text-[var(--ui-ink)] underline">
                    Open WhatsApp
                  </a>
                </div>
              ) : (
                <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">
                  Connect a WhatsApp number (Channels page) to get a tappable link — until then, send the code yourself.
                </p>
              )}
            </>
          ) : (
            <button type="button" disabled={busy !== null} onClick={() => void mint()} className={`${BTN_PRIMARY} mt-3 w-full disabled:opacity-40`}>
              {busy === "code" ? "Minting…" : "Mint handoff code"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
