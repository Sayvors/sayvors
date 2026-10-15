"use client";

import { useEffect, useMemo, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  Pill,
  SectionTitle,
  Table,
  TableScroll,
  Td,
  Th,
} from "../admin-ui";

/* ── shapes mirror ReviewIssueOut in channels/review_issues.py ─────────── */

interface ReviewIssue {
  id: string;
  tenant_id: string;
  channel_id: string;
  review_id: string;
  ticket_number: string | null;
  handoff_code: string | null;
  rating: number;
  primary_category: string;
  subcategory: string;
  subcategory_detail: string | null;
  intent: string;
  sentiment: string;
  priority: string;
  needs_attention: boolean;
  summary: string | null;
  status: string;
  reviewer_name: string | null;
  review_text: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface IssueList {
  issues: ReviewIssue[];
  total: number;
}

const STATUSES = ["new", "open", "in_progress", "resolved", "closed"] as const;
const PRIORITIES = ["low", "normal", "high", "urgent"] as const;

const PRIORITY_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = {
  urgent: "bad",
  high: "warn",
  normal: "neutral",
  low: "neutral",
};

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = {
  new: "warn",
  open: "neutral",
  in_progress: "neutral",
  resolved: "ok",
  closed: "ok",
};

/**
 * Show one short sub-line per status, next to the status count. The counts
 * alone do not say what an operator must DO about them, and on this page the
 * actionable statuses are the ones that need a human.
 */
const STATUS_BLURB: Record<string, string> = {
  new: "Nobody has looked at these",
  open: "Waiting on a human",
  in_progress: "Someone is on it",
  resolved: "Done",
  closed: "Done, not reopened",
};

function shortId(id: string | null): string {
  if (!id) return "—";
  return id.length > 10 ? `${id.slice(0, 10)}…` : id;
}

export default function AdminReviewIssuesPage() {
  const [data, setData] = useState<IssueList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      // 200 is the API ceiling; an ops panel wants the whole queue in memory to
      // slice by status and priority without a round trip per filter.
      const d = await adminFetch<IssueList>(
        `/api/v1/reviews/issues?limit=200&offset=0`,
      );
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load review issues.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const all = data?.issues ?? [];

  const stats = useMemo(() => {
    const open = all.filter((i) => i.status === "new" || i.status === "open");
    return {
      total: data?.total ?? all.length,
      loaded: all.length,
      needsAttention: all.filter((i) => i.needs_attention).length,
      urgent: all.filter((i) => i.priority === "urgent" || i.priority === "high")
        .length,
      unresolved: open.length,
      resolved: all.filter(
        (i) => i.status === "resolved" || i.status === "closed",
      ).length,
    };
  }, [all, data]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return all.filter((i) => {
      if (statusFilter && i.status !== statusFilter) return false;
      if (priorityFilter && i.priority !== priorityFilter) return false;
      if (!needle) return true;
      // Search the fields a human would actually recognise a review by.
      return [
        i.ticket_number,
        i.handoff_code,
        i.reviewer_name,
        i.review_text,
        i.summary,
        i.subcategory_detail,
        i.primary_category,
        i.subcategory,
        i.review_id,
        i.tenant_id,
      ]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(needle));
    });
  }, [all, statusFilter, priorityFilter, q]);

  if (loading && !data) {
    return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;
  }

  return (
    <div className="admin-ui">
      <PageHeader
        title="Review issues"
        lede="Every classified Google review, the category it landed in, and whether a human owes the customer something."
      />

      {error && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Review issues unavailable" detail={error} onRetry={() => void load()} />
        </div>
      )}

      {/* The queue in one line, before the queue itself. */}
      {data && (
        <div className="mb-[var(--ad-m)] grid gap-[var(--ad-xs)] sm:grid-cols-3 lg:grid-cols-5">
          {(
            [
              ["Total issues", stats.total, false],
              ["Needs attention", stats.needsAttention, stats.needsAttention > 0],
              ["Urgent / high", stats.urgent, stats.urgent > 0],
              ["Unresolved", stats.unresolved, stats.unresolved > 0],
              ["Resolved", stats.resolved, false],
            ] as [string, number, boolean][]
          ).map(([label, value, warn]) => (
            <div
              key={label}
              className={`rounded-admin-card border p-[var(--ad-s)] ${
                warn ? "border-coral/40 bg-coral/[0.05]" : "border-card-border bg-card"
              }`}
            >
              <div className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/50">
                {label}
              </div>
              <div
                className={`mt-[var(--ad-2xs)] text-admin-read font-bold tabular-nums leading-none ${
                  warn ? "text-coral" : "text-ink"
                }`}
              >
                {value.toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filters. A filter that changes nothing is worse than none, so the
          counts beside each option are computed from the loaded queue. */}
      <div className="mb-[var(--ad-xs)] flex flex-wrap items-center gap-[var(--ad-xs)]">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          className="rounded-admin-ctl border border-ink/10 bg-card px-[var(--ad-xs)] py-[var(--ad-2xs)] text-admin-base font-semibold text-ink/75 outline-none"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")} ({all.filter((i) => i.status === s).length})
            </option>
          ))}
        </select>

        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value)}
          aria-label="Filter by priority"
          className="rounded-admin-ctl border border-ink/10 bg-card px-[var(--ad-xs)] py-[var(--ad-2xs)] text-admin-base font-semibold text-ink/75 outline-none"
        >
          <option value="">All priorities</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p} ({all.filter((i) => i.priority === p).length})
            </option>
          ))}
        </select>

        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search ticket, code, reviewer, text"
          aria-label="Search review issues"
          type="search"
          className="input-field w-full max-w-80"
        />

        <span className="text-admin-base text-ink/50">
          <span className="font-bold tabular-nums text-ink">{filtered.length}</span>{" "}
          shown
        </span>
      </div>

      <TableScroll>
        <Table minWidth={1020}>
          <thead>
            <tr className="border-b border-ink/[0.06]">
              <Th>Ticket</Th>
              <Th>Tenant</Th>
              <Th align="right">Rating</Th>
              <Th>Category</Th>
              <Th>Intent</Th>
              <Th>Sentiment</Th>
              <Th>Priority</Th>
              <Th>Status</Th>
              <Th>Handoff</Th>
              <Th>Found</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={10} className="px-[var(--ad-s)] py-[var(--ad-m)] text-center text-admin-base text-ink/45">
                  {all.length === 0
                    ? "No review issues yet. They appear here once reviews are polled and classified."
                    : "Nothing matches these filters."}
                </td>
              </tr>
            )}
            {filtered.map((i) => (
              <tr
                key={i.id}
                onClick={() => setOpenId(openId === i.id ? null : i.id)}
                className="cursor-pointer border-b border-ink/[0.04] transition hover:bg-deep-violet/[0.03]"
              >
                <Td className="font-semibold tabular-nums text-ink">
                  {i.ticket_number ?? "—"}
                </Td>
                <Td className="tabular-nums text-ink/55">{shortId(i.tenant_id)}</Td>
                <Td align="right" className="tabular-nums text-ink">{i.rating}★</Td>
                <Td className="text-ink/75">{i.primary_category.replace(/_/g, " ")}</Td>
                <Td className="text-ink/75">{i.intent.replace(/_/g, " ")}</Td>
                <Td className="text-ink/75">{i.sentiment}</Td>
                <Td>
                  <Pill tone={PRIORITY_TONE[i.priority] ?? "neutral"}>{i.priority}</Pill>
                </Td>
                <Td>
                  <Pill tone={STATUS_TONE[i.status] ?? "neutral"}>
                    {i.status.replace(/_/g, " ")}
                  </Pill>
                </Td>
                <Td className="tabular-nums text-ink/60">
                  {i.handoff_code ?? <span className="text-ink/35">none</span>}
                </Td>
                <Td className="text-ink/55">
                  {new Date(i.created_at).toLocaleDateString()}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </TableScroll>

      {openId && (
        <IssueDetail
          issue={all.find((i) => i.id === openId)!}
          onClose={() => setOpenId(null)}
          onChanged={() => void load()}
        />
      )}
    </div>
  );
}

/* ── detail ──────────────────────────────────────────────────────────── */

function IssueDetail({
  issue,
  onClose,
  onChanged,
}: {
  issue: ReviewIssue;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(issue.handoff_code);

  async function setStatus(status: string) {
    setBusy(status);
    setError(null);
    try {
      await adminFetch(`/api/v1/reviews/issues/${issue.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the issue.");
    } finally {
      setBusy(null);
    }
  }

  async function mintCode() {
    setBusy("code");
    setError(null);
    try {
      const row = await adminFetch<ReviewIssue>(
        `/api/v1/reviews/issues/${issue.id}/handoff-code`,
        { method: "POST" },
      );
      setCode(row.handoff_code);
    } catch (e) {
      // 422 means "needs no attention, nothing to hand off" -- a fact about
      // the issue, not a failure of the request.
      setError(e instanceof Error ? e.message : "Could not mint a code.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close issue detail"
        onClick={onClose}
        className="absolute inset-0 bg-ink/30"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Issue ${issue.ticket_number ?? issue.review_id}`}
        className="admin-ui relative h-full w-full max-w-2xl overflow-y-auto border-l border-card-border bg-fog p-[var(--ad-m)]"
      >
        <div className="mb-[var(--ad-m)] flex items-start justify-between gap-[var(--ad-s)]">
          <div>
            <h2 className="text-admin-lg font-bold text-ink">
              {issue.ticket_number ?? "Unticketed"}
            </h2>
            <p className="mt-[var(--ad-3xs)] text-admin-base text-ink/50">
              {issue.primary_category.replace(/_/g, " ")} ·{" "}
              {issue.subcategory.replace(/_/g, " ")} · found{" "}
              {new Date(issue.created_at).toLocaleString()}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="admin-btn border border-ink/10 px-[var(--ad-xs)] py-1 text-admin-base text-ink/60"
          >
            Close
          </button>
        </div>

        <div className="mb-[var(--ad-m)] flex flex-wrap gap-[var(--ad-xs)]">
          <Pill tone={PRIORITY_TONE[issue.priority] ?? "neutral"}>{issue.priority}</Pill>
          <Pill tone={STATUS_TONE[issue.status] ?? "neutral"}>
            {issue.status.replace(/_/g, " ")}
          </Pill>
          <Pill tone={issue.sentiment === "negative" ? "bad" : issue.sentiment === "positive" ? "ok" : "neutral"}>
            {issue.sentiment}
          </Pill>
          <Pill tone="neutral">{issue.rating}★</Pill>
          {issue.needs_attention && <Pill tone="bad">needs attention</Pill>}
        </div>

        {error && (
          <p role="alert" className="mb-[var(--ad-s)] rounded-admin-ctl bg-coral/10 px-[var(--ad-xs)] py-[var(--ad-2xs)] text-admin-base font-medium text-coral">
            {error}
          </p>
        )}

        <Panel className="mb-[var(--ad-s)]">
          <SectionTitle>Customer context</SectionTitle>
          <dl className="space-y-[var(--ad-3xs)] text-admin-base">
            {(
              [
                ["Reviewer", issue.reviewer_name ?? "not named"],
                ["Tenant", shortId(issue.tenant_id)],
                ["Channel", shortId(issue.channel_id)],
                ["Review id", shortId(issue.review_id)],
                ["Intent", issue.intent.replace(/_/g, " ")],
                ["Subcategory detail", issue.subcategory_detail],
                ["Summary", issue.summary],
              ] as [string, string | null][]
            ).map(([k, v]) => (
              <div key={k} className="flex gap-[var(--ad-xs)]">
                <dt className="w-36 shrink-0 text-ink/50">{k}</dt>
                <dd className="min-w-0 break-words text-ink">{v ?? "—"}</dd>
              </div>
            ))}
          </dl>
        </Panel>

        {issue.review_text && (
          <Panel className="mb-[var(--ad-s)]">
            <SectionTitle>The review</SectionTitle>
            <p className="whitespace-pre-wrap text-admin-base text-ink/85">
              {issue.review_text}
            </p>
          </Panel>
        )}

        <Panel className="mb-[var(--ad-s)]">
          <SectionTitle>Set status</SectionTitle>
          <div className="flex flex-wrap gap-[var(--ad-2xs)]">
            {STATUSES.filter((s) => s !== issue.status).map((s) => (
              <button
                key={s}
                type="button"
                disabled={busy !== null}
                onClick={() => void setStatus(s)}
                className="admin-btn border border-ink/10 text-ink/70 hover:bg-ink/[0.04] disabled:opacity-40"
              >
                {s.replace(/_/g, " ")}
              </button>
            ))}
          </div>
          <p className="mt-[var(--ad-xs)] text-admin-micro text-ink/45">
            {STATUS_BLURB[issue.status]}
          </p>
        </Panel>

        <Panel>
          <SectionTitle>WhatsApp handoff</SectionTitle>
          <p className="mb-[var(--ad-xs)] text-admin-base text-ink/60">
            {code
              ? "Quote this to the customer. It is what links their WhatsApp message to this review."
              : "Mint a code the customer can quote on WhatsApp, so their message is recognised instead of re-interviewed."}
          </p>
          {code ? (
            <p className="rounded-admin-ctl bg-deep-violet/[0.06] px-[var(--ad-xs)] py-[var(--ad-2xs)] text-center text-admin-md font-bold tabular-nums tracking-[0.2em] text-deep-violet">
              {code}
            </p>
          ) : (
            <button
              type="button"
              disabled={busy !== null}
              aria-busy={busy === "code"}
              onClick={() => void mintCode()}
              className="admin-btn w-full bg-deep-violet text-white hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {busy === "code" ? "Minting…" : "Mint handoff code"}
            </button>
          )}
        </Panel>
      </div>
    </div>
  );
}