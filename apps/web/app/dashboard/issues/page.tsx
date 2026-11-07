"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  LocationIssue,
  fetchIssues,
  refreshIssues,
  updateIssue,
} from "@/lib/api-analytics";
import { apiFetch } from "@/lib/api-rag";
import { safeHref } from "@/lib/safe-url";
import CustomerAvatar from "@/components/customers/CustomerAvatar";
import GoogleBusinessLogo from "@/components/channels/GoogleBusinessLogo";

/**
 * Google review issues: the problems named in negative reviews, per location.
 *
 * The page speaks Google's language on purpose — reviewer identity, stars,
 * review dates and "View on Google" links — so a merchant can verify every
 * quote instead of trusting a summary. Status remains the merchant's: a
 * refresh moves the evidence forward but never reopens or closes an issue.
 */

const STATUS_ORDER: LocationIssue["status"][] = [
  "open",
  "in_progress",
  "done",
  "dismissed",
];

const STATUS_LABEL: Record<LocationIssue["status"], string> = {
  open: "To fix",
  in_progress: "In progress",
  done: "Fixed",
  dismissed: "Not a problem",
};

const STATUS_STYLE: Record<LocationIssue["status"], string> = {
  open: "bg-coral/10 text-coral ring-1 ring-coral/25",
  in_progress: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  done: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  dismissed: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)] ring-1 ring-[var(--ui-line)]",
};

function Stars({ rating, size = 12 }: { rating: number; size?: number }) {
  const value = Math.max(0, Math.min(5, Math.round(rating)));
  return (
    <span
      className="inline-flex items-center gap-0.5 text-[#FBBC05]"
      style={{ fontSize: size }}
      aria-label={`${value} out of 5 stars`}
    >
      {Array.from({ length: 5 }).map((_, index) => (
        <span key={index} aria-hidden className={index < value ? "" : "opacity-25"}>
          ★
        </span>
      ))}
    </span>
  );
}

function StatusPill({ status }: { status: LocationIssue["status"] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${STATUS_STYLE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

function evidenceDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** One issue, expandable to the Google reviews behind it. */
function IssueRow({
  issue,
  onUpdate,
  updating,
  showLocation,
}: {
  issue: LocationIssue;
  onUpdate: (patch: { status?: LocationIssue["status"]; resolution_note?: string | null }) => void;
  updating: boolean;
  showLocation: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(issue.resolution_note ?? "");
  const [savingNote, setSavingNote] = useState(false);

  const saveNote = async () => {
    setSavingNote(true);
    try {
      onUpdate({ resolution_note: note });
    } finally {
      setSavingNote(false);
    }
  };

  const closed = issue.status === "done" || issue.status === "dismissed";

  return (
    <article
      className={`overflow-hidden rounded-2xl border bg-[var(--ui-surface)] transition ${
        closed
          ? "border-[var(--ui-line)] opacity-80"
          : "border-[var(--ui-line)] hover:border-deep-violet/25"
      }`}
    >
      <div className="p-3.5 sm:p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="min-w-0 flex-1 rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40"
          >
            <div className="flex flex-wrap items-center gap-2">
              {showLocation && issue.channel_name && (
                <span className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[9.5px] font-semibold text-[var(--ui-ink)]">
                  <GoogleBusinessLogo size={11} />
                  <span className="truncate">{issue.channel_name}</span>
                </span>
              )}
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">
                {issue.subject_label}
              </h3>
              <StatusPill status={issue.status} />
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-[var(--ui-ink-2)]">
              <Stars rating={issue.avg_rating} />
              <span className="font-semibold text-[var(--ui-ink)]">
                {issue.negative_count} of {issue.review_count} review
                {issue.review_count === 1 ? "" : "s"} negative
              </span>
              <span>average {issue.avg_rating.toFixed(1)}</span>
            </div>

            {issue.title && (
              <p className="mt-2 text-[12.5px] leading-5 text-[var(--ui-ink)]">
                <span className="font-semibold">Fix:</span> {issue.title}
              </p>
            )}

            <p className="mt-2 inline-flex items-center gap-1 text-[10.5px] font-semibold text-[var(--ui-ink-2)]">
              {open
                ? "Hide reviews"
                : issue.evidence.length > 0
                  ? `Read the ${issue.evidence.length} review${issue.evidence.length === 1 ? "" : "s"}`
                  : "Open details"}
              <span aria-hidden className={`transition ${open ? "rotate-180" : ""}`}>⌄</span>
            </p>
          </button>

          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            {issue.status === "open" && (
              <button
                type="button"
                onClick={() => onUpdate({ status: "in_progress" })}
                disabled={updating}
                className="rounded-lg border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1.5 text-[10.5px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] disabled:opacity-40"
              >
                Start
              </button>
            )}
            {issue.status !== "done" && (
              <button
                type="button"
                onClick={() => onUpdate({ status: "done" })}
                disabled={updating}
                className="rounded-lg bg-deep-violet px-2.5 py-1.5 text-[10.5px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
              >
                Mark fixed
              </button>
            )}
            {issue.status === "done" && (
              <button
                type="button"
                onClick={() => onUpdate({ status: "open" })}
                disabled={updating}
                className="rounded-lg border border-[var(--ui-line)] px-2.5 py-1.5 text-[10.5px] font-medium text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] disabled:opacity-40"
              >
                Reopen
              </button>
            )}
            {(issue.status === "open" || issue.status === "in_progress") && (
              <button
                type="button"
                onClick={() => onUpdate({ status: "dismissed" })}
                disabled={updating}
                title="Not a real problem — record that decision separately from fixing it"
                className="rounded-lg px-2 py-1.5 text-[10.5px] text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] disabled:opacity-40"
              >
                Not a problem
              </button>
            )}
            {issue.status === "dismissed" && (
              <button
                type="button"
                onClick={() => onUpdate({ status: "open" })}
                disabled={updating}
                className="rounded-lg border border-[var(--ui-line)] px-2.5 py-1.5 text-[10.5px] font-medium text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] disabled:opacity-40"
              >
                Reopen
              </button>
            )}
          </div>
        </div>
      </div>

      {open && (
        <div className="border-t border-[var(--ui-line)] bg-[var(--ui-surface)] px-3.5 py-3.5 sm:px-4">
          {issue.detail && (
            <div className="rounded-xl border-l-2 border-deep-violet/50 bg-[var(--ui-sunken)] px-3 py-2.5">
              <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">
                What to do
              </p>
              <p className="mt-1 text-[12px] leading-5 text-[var(--ui-ink)]">
                {issue.detail}
              </p>
            </div>
          )}

          <div className="mt-3 flex items-center justify-between gap-2">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">
              What customers actually said
            </p>
            <Link
              href="/dashboard/reviews"
              className="text-[10.5px] font-semibold text-[#1a73e8] hover:underline"
            >
              Open Google reviews
            </Link>
          </div>

          {issue.evidence.length === 0 ? (
            <p className="mt-1.5 rounded-xl bg-[var(--ui-sunken)] px-3 py-2 text-[12px] text-[var(--ui-ink-2)]">
              No verbatim quotes were captured for this one.
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {issue.evidence.map((e, index) => {
                const href = e.review_url ? safeHref(e.review_url) : null;
                return (
                  <li
                    key={`${e.review_id}-${index}`}
                    className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-2.5"
                  >
                    <div className="flex items-start gap-2.5">
                      <CustomerAvatar
                        name={e.reviewer ?? null}
                        url={e.reviewer_photo_url ?? null}
                        size="sm"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="text-[11.5px] font-semibold text-[var(--ui-ink)]">
                            {e.reviewer || "Google reviewer"}
                          </span>
                          <Stars rating={e.rating} size={11} />
                          {e.reviewed_at && (
                            <span className="text-[9.5px] text-[var(--ui-ink-2)]">
                              {evidenceDate(e.reviewed_at)}
                            </span>
                          )}
                        </div>
                        <p
                          className="mt-1 text-[12px] leading-5 text-[var(--ui-ink)]"
                          dir="auto"
                        >
                          “{e.quote}”
                        </p>
                        {href && (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1 inline-flex items-center gap-1 text-[10.5px] font-semibold text-[#1a73e8] hover:underline"
                          >
                            View on Google
                            <span aria-hidden>↗</span>
                          </a>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <label className="mt-3 block">
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">
              What you did about it
            </span>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={2}
              maxLength={2000}
              placeholder="Deep clean booked for Monday, contractor confirmed…"
              className="mt-1 w-full resize-y rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12.5px] leading-5 text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
            />
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={saveNote}
              disabled={savingNote}
              className="rounded-lg bg-[var(--ui-ink)] px-3 py-1.5 text-[11px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 disabled:opacity-40"
            >
              {savingNote ? "Saving…" : "Save note"}
            </button>
            {issue.resolved_at && (
              <span className="text-[10.5px] text-[var(--ui-ink-2)]">
                Resolved {new Date(issue.resolved_at).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

function IssuesContent() {
  const [issues, setIssues] = useState<LocationIssue[]>([]);
  const [heldOut, setHeldOut] = useState({ total: 0, reviewable: 0, reviews: 0 });
  const [channels, setChannels] = useState<{ id: string; name: string }[]>([]);
  const [channel, setChannel] = useState<string>("");
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/v1/channels?limit=100")
      .then((data: { channels?: { id: string; platform: string; display_name: string | null }[] }) => {
        setChannels(
          (data.channels ?? [])
            .filter((c) => c.platform === "google_reviews")
            .map((c) => ({ id: c.id, name: c.display_name ?? "Google location" }))
        );
      })
      .catch(() => setChannels([]));
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchIssues({ channelId: channel || null });
      setIssues(data.items);
      setHeldOut(data.held_out ?? { total: 0, reviewable: 0, reviews: 0 });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load issues.");
    } finally {
      setLoadedFor(channel);
    }
  }, [channel]);

  useEffect(() => {
    load();
  }, [load]);

  const loading = loadedFor !== channel;

  const doRefresh = async () => {
    setRefreshing(true);
    try {
      const res = await refreshIssues(channel || null);
      setNote(
        `Checked ${res.created} new and updated ${res.updated} issue${
          res.updated === 1 ? "" : "s"
        }. Your statuses were left alone.`
      );
      await load();
    } catch {
      setError("Could not refresh issues.");
    } finally {
      setRefreshing(false);
      setTimeout(() => setNote(null), 5000);
    }
  };

  const applyUpdate = async (
    issue: LocationIssue,
    patch: { status?: LocationIssue["status"]; resolution_note?: string | null }
  ) => {
    setUpdatingId(issue.id);
    try {
      const updated = await updateIssue(issue.id, patch);
      setIssues((prev) =>
        [...prev.filter((i) => i.id !== issue.id), updated].sort(
          (a, b) => b.negative_count - a.negative_count
        )
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that change.");
    } finally {
      setUpdatingId(null);
    }
  };

  const grouped = useMemo(() => {
    const byStatus: Record<string, LocationIssue[]> = {};
    for (const s of STATUS_ORDER) byStatus[s] = [];
    for (const i of issues) (byStatus[i.status] ??= []).push(i);
    return byStatus;
  }, [issues]);

  const summary = useMemo(() => {
    const totalReviews = issues.reduce((sum, issue) => sum + issue.review_count, 0);
    const weighted = issues.reduce(
      (sum, issue) => sum + issue.avg_rating * issue.review_count,
      0
    );
    return {
      open: grouped.open?.length ?? 0,
      inProgress: grouped.in_progress?.length ?? 0,
      fixed: grouped.done?.length ?? 0,
      avgRating: totalReviews > 0 ? weighted / totalReviews : 0,
    };
  }, [grouped, issues]);

  return (
    <div className="team-ui h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-4xl space-y-4 p-3 sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[var(--ui-ink-2)]">
              <GoogleBusinessLogo size={20} />
              <span className="text-[10px] font-bold uppercase tracking-[0.16em]">
                Google Business Profile
              </span>
            </div>
            <h1 className="mt-1 text-[20px] font-bold tracking-tight text-[var(--ui-ink)] sm:text-[24px]">
              Review issues
            </h1>
            <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-[var(--ui-ink-2)] sm:text-[13px]">
              What customers complained about in your Google reviews, and what
              to do about it. Every quote opens back to the original review.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
              aria-label="Location"
              className="h-9 min-w-0 flex-1 rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 text-[11px] font-semibold text-[var(--ui-ink)] outline-none sm:flex-none"
            >
              <option value="">All locations</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={doRefresh}
              disabled={refreshing}
              className="h-9 rounded-xl bg-deep-violet px-3.5 text-[11.5px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 active:translate-y-px disabled:opacity-50"
            >
              {refreshing ? "Checking…" : "Re-check reviews"}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: "To fix", value: summary.open, tone: "text-coral" },
            { label: "In progress", value: summary.inProgress, tone: "text-amber-700" },
            { label: "Fixed", value: summary.fixed, tone: "text-emerald-700" },
            { label: "Issue avg", value: summary.avgRating ? `${summary.avgRating.toFixed(1)}★` : "—", tone: "text-[var(--ui-ink)]" },
          ].map((stat) => (
            <div key={stat.label} className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2.5">
              <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
                {stat.label}
              </p>
              <p className={`mt-1 text-[18px] font-bold tabular-nums ${stat.tone}`}>
                {stat.value}
              </p>
            </div>
          ))}
        </div>

        {note && (
          <p className="rounded-xl bg-emerald-50 px-3 py-2 text-[12px] text-emerald-800 ring-1 ring-emerald-200">
            {note}
          </p>
        )}
        {error && (
          <p className="rounded-xl bg-coral/10 px-3 py-2 text-[12px] text-coral ring-1 ring-coral/20">
            {error}
          </p>
        )}

        {heldOut.total > 0 && (
          <p className="rounded-xl bg-amber-50 px-3 py-2 text-[12px] text-amber-800 ring-1 ring-amber-200">
            {heldOut.total} of {heldOut.reviews} review
            {heldOut.reviews === 1 ? "" : "s"} could not be read confidently, so
            they are not counted here.{" "}
            <Link
              href="/dashboard/reviews?tab=needs_human"
              className="font-semibold underline underline-offset-2"
            >
              Check them
            </Link>
          </p>
        )}

        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)]"
                aria-hidden
              />
            ))}
          </div>
        ) : issues.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[var(--ui-line-strong)] bg-[var(--ui-surface)] p-8 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[var(--ui-sunken)]">
              <GoogleBusinessLogo size={28} />
            </div>
            <p className="mt-3 text-[14px] font-semibold text-[var(--ui-ink)]">
              No issues found
            </p>
            <p className="mx-auto mt-1 max-w-sm text-[12px] leading-5 text-[var(--ui-ink-2)]">
              Issues appear when negative Google reviews name something
              specific. If you just connected a location, re-check after the
              first sync.
            </p>
            <button
              type="button"
              onClick={doRefresh}
              disabled={refreshing}
              className="mt-4 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {refreshing ? "Checking…" : "Re-check reviews"}
            </button>
          </div>
        ) : (
          <>
            {STATUS_ORDER.filter((s) => s !== "dismissed").map((status) => {
              const group = grouped[status] ?? [];
              if (group.length === 0) return null;
              return (
                <section key={status}>
                  <h2 className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">
                    {STATUS_LABEL[status]}
                    <span className="rounded-full bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[9px]">
                      {group.length}
                    </span>
                  </h2>
                  <div className="space-y-2">
                    {group.map((i) => (
                      <IssueRow
                        key={i.id}
                        issue={i}
                        updating={updatingId === i.id}
                        showLocation={!channel}
                        onUpdate={(p) => applyUpdate(i, p)}
                      />
                    ))}
                  </div>
                </section>
              );
            })}

            {(grouped.dismissed ?? []).length > 0 && (
              <details className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3">
                <summary className="cursor-pointer text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">
                  Not a problem
                  <span className="ml-1.5 font-semibold">
                    {grouped.dismissed.length}
                  </span>
                </summary>
                <div className="mt-2 space-y-2">
                  {grouped.dismissed.map((i) => (
                    <IssueRow
                      key={i.id}
                      issue={i}
                      updating={updatingId === i.id}
                      showLocation={!channel}
                      onUpdate={(p) => applyUpdate(i, p)}
                    />
                  ))}
                </div>
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function IssuesPage() {
  return <IssuesContent />;
}
