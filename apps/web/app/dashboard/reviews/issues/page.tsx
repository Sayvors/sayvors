"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { useUpdateReviewIssue } from "@/lib/mutation-hooks";
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
import { fetchAssignees, type Assignee } from "@/lib/api-inbox";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type TicketsDict = Dict["reviews"]["tickets"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

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
  const { user } = useAuth();
  const { t, locale } = useI18n();
  const kt = t.reviews.tickets;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const stLabel = (s: string) => kt.status[s as keyof typeof kt.status] ?? label(s);
  const prLabel = (s: string) => kt.priority[s as keyof typeof kt.priority] ?? label(s);
  const [statusFilter, setStatusFilter] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState<"all" | "mine">("all");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [waPhone, setWaPhone] = useState<string | null>(null);
  const [assignees, setAssignees] = useState<Assignee[]>([]);

  // `silent` keeps the list mounted during a realtime refresh: a ticket
  // appearing must not blank the page the merchant is reading. TanStack Query
  // handles this via isFetching (background) vs isPending (first load).
  const queryClient = useQueryClient();
  const issuesQuery = useQuery({
    queryKey: queryKeys.reviewIssues.list("", true, 200),
    queryFn: () => fetchReviewIssues({ ticketed: true, limit: 200 }),
    staleTime: 30 * 1000,
  });
  const issues = issuesQuery.data?.issues ?? [];
  const total = issuesQuery.data?.total ?? 0;
  const loading = issuesQuery.isPending;
  const error = issuesQuery.isError
    ? issuesQuery.error instanceof Error
      ? issuesQuery.error.message
      : kt.loadFailed
    : null;

  // Live tickets. One poll loop classified a review and opened a ticket while
  // nobody was on this page — a customer complaining, then walking in on
  // WhatsApp — so the queue refetches itself on every lifecycle change.
  // Coalesced: a new ticket arrives as `created` plus `handoff_minted`, and
  // a customer returning can chain further updates; without the window that
  // is several redundant fetches for one row.
  const burst = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshQuietly = useCallback(() => {
    if (burst.current) clearTimeout(burst.current);
    burst.current = setTimeout(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.reviewIssues.all() });
    }, 400);
  }, [queryClient]);

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
        if (assigneeFilter === "mine" && (!user || i.assigned_to !== user.id)) {
          return false;
        }
        if (!needle) return true;
        return [i.ticket_number, i.handoff_code, i.reviewer_name, i.review_text, i.summary, i.primary_category, i.subcategory, i.subcategory_detail]
          .filter(Boolean)
          .some((v) => (v as string).toLowerCase().includes(needle));
      })
      .sort((a, b) => (priorityRank[a.priority] ?? 2) - (priorityRank[b.priority] ?? 2));
  }, [issues, statusFilter, assigneeFilter, user, q]);

  const listRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => listRef.current,
    estimateSize: () => 88,
    overscan: 6,
  });

  const open = openId ? issues.find((i) => i.id === openId) ?? null : null;
  const openChannel = open?.channel_id ?? null;

  // Eligible owners for the open ticket's channel. The drawer needs names and
  // ids; the server filters out teammates who cannot work that channel.
  useEffect(() => {
    if (!openChannel) {
      setAssignees([]);
      return;
    }
    let cancelled = false;
    fetchAssignees(openChannel)
      .then((people) => {
        if (!cancelled) setAssignees(people);
      })
      .catch(() => {
        if (!cancelled) setAssignees([]);
      });
    return () => {
      cancelled = true;
    };
  }, [openChannel]);

  return (
    <div className="team-ui h-full overflow-y-auto px-6 py-6 pb-24">
      <div className="mx-auto max-w-5xl">
        {/* ── header ─────────────────────────────────────────── */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-bold text-[var(--ui-ink)]">{kt.title}</h1>
            <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
              {kt.body}
            </p>
          </div>
          <button type="button" onClick={() => void issuesQuery.refetch()} disabled={issuesQuery.isFetching} className={BTN_GHOST}>
            {loading ? kt.loading : kt.refresh}
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
              [kt.queueUnresolved, stats.unresolved],
              [kt.queueAttention, stats.attention],
              [kt.queueUrgent, stats.urgent],
              [kt.queueResolved, stats.resolved],
            ] as [string, number][]
          ).map(([k, v]) => (
            <div
              key={k}
              className={`ui-panel px-4 py-3 ${k === kt.queueUrgent && v > 0 ? "border-red-500" : ""}`}
            >
              <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{k}</div>
              <div className={`mt-1 text-[24px] font-bold leading-none tabular-nums ${k === kt.queueUrgent && v > 0 ? "text-red-600" : "text-[var(--ui-ink)]"}`}>{fmt(v)}</div>
            </div>
          ))}
        </div>

        {/* ── filters ────────────────────────────────────────── */}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label={kt.filterStatusAria}
            className="ui-input w-auto bg-[var(--ui-surface)] px-3 py-2 text-[13px] font-semibold text-[var(--ui-ink)]"
          >
            <option value="">{kt.allStatuses}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {stLabel(s)} ({fmt(issues.filter((i) => i.status === s).length)})
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() =>
              setAssigneeFilter((v) => (v === "mine" ? "all" : "mine"))
            }
            aria-pressed={assigneeFilter === "mine"}
            className={`ui-btn px-3 py-2 text-[13px] font-semibold ${
              assigneeFilter === "mine"
                ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                : "bg-[var(--ui-surface)] text-[var(--ui-ink)]"
            }`}
          >
            {kt.mine}
          </button>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={kt.searchPh}
            aria-label={kt.searchAria}
            type="search"
            className="ui-input w-full max-w-72 bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] placeholder:text-[var(--ui-ink-2)]"
          />
          <span className="text-[12px] text-[var(--ui-ink-2)]">
            <span className="font-bold tabular-nums text-[var(--ui-ink)]">{fmt(filtered.length)}</span> {kt.shown}
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
              {issues.length === 0 ? kt.emptyNone : kt.emptyFiltered}
            </p>
            <p className="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
              {issues.length === 0
                ? <>{kt.emptyNoneBody} {total > 0 ? fill(kt.emptyNoneLoaded, { n: fmt(total) }) : ""}</>
                : kt.emptyFilteredBody}
            </p>
          </div>
        ) : (
          <div
            ref={listRef}
            className="ui-panel mt-4 max-h-[70vh] overflow-y-auto divide-y divide-[var(--ui-line)]"
          >
            <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative", width: "100%" }}>
              {rowVirtualizer.getVirtualItems().map((vi) => {
                const i = filtered[vi.index];
                return (
                  <button
                    key={i.id}
                    type="button"
                    onClick={() => setOpenId(i.id)}
                    data-index={vi.index}
                    ref={rowVirtualizer.measureElement}
                    className={`block w-full px-4 py-3.5 text-left transition hover:bg-[var(--ui-sunken)] ${
                      i.priority === "urgent"
                        ? "border-l-4 border-red-500 bg-red-50"
                        : i.priority === "high"
                          ? "border-l-4 border-amber-500 bg-amber-50"
                          : ""
                    }`}
                    style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-bold tabular-nums text-[var(--ui-ink)]">{i.ticket_number ?? kt.unticketed}</span>
                      <Chip strong={i.priority === "urgent" || i.priority === "high"}>{prLabel(i.priority)}</Chip>
                      <Chip strong={UNRESOLVED.has(i.status)}>{stLabel(i.status)}</Chip>
                      <span className="ml-auto text-[12px] text-[var(--ui-ink-2)]">{new Date(i.created_at).toLocaleDateString(dateLocale)}</span>
                    </div>
                    <p className="mt-1.5 truncate text-[13px] text-[var(--ui-ink)]">
                      {i.summary || i.review_text || label(i.primary_category)}
                    </p>
                    <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                      {label(i.primary_category)} · {label(i.subcategory)}
                      {i.assigned_to ? (
                        <>
                          {" · "}
                          <span className="font-semibold text-[var(--ui-ink)]">
                            {i.assigned_to === user?.id ? kt.you : kt.assigned}
                          </span>
                        </>
                      ) : (
                        <>{" · "}{kt.unassigned}</>
                      )}
                      {i.handoff_code && <> · {kt.codePrefix} <span className="font-semibold tabular-nums text-[var(--ui-ink)]">#{i.handoff_code}</span></>}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {open && (
        <TicketDrawer
          issue={open}
          waPhone={waPhone}
          assignees={assignees}
          onClose={() => setOpenId(null)}
          onChanged={(row) =>
            queryClient.setQueryData(queryKeys.reviewIssues.list("", true, 200), (old: { issues: ReviewIssue[]; total: number } | undefined) =>
              old ? { ...old, issues: old.issues.map((x) => (x.id === row.id ? row : x)) } : old,
            )
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
function describeExpiry(
  iso: string | null,
  ex: { expired: string; minutes: string; hours: string; days: string },
  fmt: (n: number) => string,
): string | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms)) return null;
  if (ms <= 0) return ex.expired;
  const minutes = Math.ceil(ms / 60_000);
  if (minutes < 60) return fill(ex.minutes, { n: fmt(minutes) });
  const hours = Math.ceil(minutes / 60);
  if (hours < 48) return fill(ex.hours, { n: fmt(hours) });
  return fill(ex.days, { n: fmt(Math.ceil(hours / 24)) });
}

function TicketDrawer({
  issue,
  waPhone,
  assignees,
  onClose,
  onChanged,
}: {
  issue: ReviewIssue;
  waPhone: string | null;
  assignees: Assignee[];
  onClose: () => void;
  onChanged: (row: ReviewIssue) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();
  const { t, locale } = useI18n();
  const kt = t.reviews.tickets;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const stLabel = (s: string) => kt.status[s as keyof typeof kt.status] ?? label(s);
  const prLabel = (s: string) => kt.priority[s as keyof typeof kt.priority] ?? label(s);
  const updateIssue = useUpdateReviewIssue();
  const [code, setCode] = useState<string | null>(issue.handoff_code);
  const [expiresAt, setExpiresAt] = useState<string | null>(
    issue.handoff_code_expires_at,
  );
  const [copied, setCopied] = useState(false);

  const link = code ? waMeLink(waPhone, code) : "";
  const expired = !!expiresAt && new Date(expiresAt).getTime() <= Date.now();
  const expiryLabel = describeExpiry(expiresAt, { expired: kt.expired, minutes: kt.expiresMin, hours: kt.expiresHours, days: kt.expiresDays }, fmt);

  async function setStatus(status: string) {
    setBusy(status);
    setError(null);
    try {
      const row = await updateIssue.mutateAsync({ id: issue.id, patch: { status } });
      onChanged(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : kt.updateFailed);
    } finally {
      setBusy(null);
    }
  }

  async function setAssignee(assignedTo: string | null) {
    setBusy("assignee");
    setError(null);
    try {
      const row = await updateIssue.mutateAsync({
        id: issue.id,
        patch: { assigned_to: assignedTo },
      });
      onChanged(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : kt.assignFailed);
    } finally {
      setBusy(null);
    }
  }

  const assigneeMissing =
    !!issue.assigned_to &&
    !assignees.some((a) => a.user_id === issue.assigned_to);

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
      setError(e instanceof Error ? e.message : kt.mintFailed);
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
        aria-label={kt.drawerCloseAria}
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={fill(kt.drawerAria, { n: issue.ticket_number ?? issue.review_id })}
        className="team-ui relative h-full w-full max-w-xl overflow-y-auto border-l border-[var(--ui-line)] bg-[var(--ui-page)] p-5"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[18px] font-bold text-[var(--ui-ink)]">{issue.ticket_number ?? kt.unticketed}</h2>
            <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
              {label(issue.primary_category)} · {label(issue.subcategory)} · {fill(kt.found, { when: new Date(issue.created_at).toLocaleString(dateLocale) })}
            </p>
          </div>
          <button type="button" onClick={onClose} className={`${UI_BTN} bg-[var(--ui-surface)] px-4 py-2 text-[var(--ui-ink)]`}>
            {kt.close}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip strong={issue.priority === "urgent" || issue.priority === "high"}>{prLabel(issue.priority)}</Chip>
          <Chip strong={UNRESOLVED.has(issue.status)}>{stLabel(issue.status)}</Chip>
          <Chip>{issue.sentiment}</Chip>
          <Chip>{fmt(issue.rating)}★</Chip>
          {issue.needs_attention && <Chip strong>{kt.needsAttention}</Chip>}
        </div>

        {error && (
          <p role="alert" className="mt-3 border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-2.5 text-[13px] font-medium text-[var(--ui-ink)]">
            {error}
          </p>
        )}

        {issue.review_text && (
          <div className="ui-panel mt-4 px-4 py-3">
            <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{kt.reviewTitle}</div>
            <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-[var(--ui-ink)]">{issue.review_text}</p>
          </div>
        )}

        <div className="ui-panel mt-3 px-4 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{kt.understoodTitle}</div>
          <dl className="mt-1.5 space-y-1.5 text-[13px]">
            {(
              [
                [kt.reviewer, issue.reviewer_name ?? kt.notNamed],
                [kt.intent, label(issue.intent)],
                [kt.detail, issue.subcategory_detail],
                [kt.summary, issue.summary],
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
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{kt.ownerTitle}</div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
            {kt.ownerBody}
          </p>
          <select
            value={issue.assigned_to ?? ""}
            disabled={busy !== null}
            onChange={(e) => void setAssignee(e.target.value || null)}
            aria-label={kt.ownerAria}
            className="ui-input mt-2 w-full bg-[var(--ui-surface)] px-3 py-2 text-[13px] font-semibold text-[var(--ui-ink)] disabled:opacity-40"
          >
            <option value="">{kt.unassignedOpt}</option>
            {assigneeMissing && issue.assigned_to && (
              <option value={issue.assigned_to}>{kt.assignedOpt}</option>
            )}
            {assignees.map((a) => (
              <option key={a.user_id} value={a.user_id}>
                {a.name}
                {a.user_id === user?.id ? kt.youSuffix : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="ui-panel mt-3 px-4 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{kt.statusTitle}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {STATUSES.filter((s) => s !== issue.status).map((s) => (
              <button
                key={s}
                type="button"
                disabled={busy !== null}
                onClick={() => void setStatus(s)}
                className={`${UI_BTN} border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[var(--ui-ink)] disabled:opacity-40`}
              >
                {busy === s ? kt.saving : stLabel(s)}
              </button>
            ))}
          </div>
        </div>

        <div className="ui-panel mt-3 px-4 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{kt.handoffTitle}</div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
            {code ? kt.handoffHasCode : kt.handoffNoCode}
          </p>
          {code ? (
            <>
              <p className="mt-3 bg-[var(--ui-sunken)] px-4 py-3 text-center text-[18px] font-bold tabular-nums tracking-[0.2em] text-[var(--ui-ink)]">
                #{code}
              </p>
              <p className="mt-1 text-center text-[11px] text-[var(--ui-ink-2)]">
                {expiryLabel ? fill(kt.codeLine, { label: expiryLabel }) : kt.legacyCode}
              </p>
              {expired ? (
                <div className="mt-2">
                  <p className="text-[12px] text-[var(--ui-ink-2)]">
                    {kt.expiredBody}
                  </p>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void mint()}
                    className={`${BTN_PRIMARY} mt-2 disabled:opacity-40`}
                  >
                    {busy === "code" ? kt.minting : kt.mintNew}
                  </button>
                </div>
              ) : link ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => void copyLink()} className={BTN_PRIMARY}>
                    {copied ? kt.copied : kt.copyLink}
                  </button>
                  <a href={link} target="_blank" rel="noreferrer" className="text-[12px] font-semibold text-[var(--ui-ink)] underline">
                    {kt.openWa}
                  </a>
                </div>
              ) : (
                <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">
                  {kt.noWaPhone}
                </p>
              )}
            </>
          ) : (
            <button type="button" disabled={busy !== null} onClick={() => void mint()} className={`${BTN_PRIMARY} mt-3 w-full disabled:opacity-40`}>
              {busy === "code" ? kt.minting : kt.mintCode}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
