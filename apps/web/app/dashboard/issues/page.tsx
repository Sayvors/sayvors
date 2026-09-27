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

/**
 * Issues: the list of things to actually fix, per location.
 *
 * This replaces the dashboard's "Fix this →" link, which pointed at the review
 * list. It named the dimension costing the most stars and handed back reading
 * material, so the promise and the destination did not match.
 *
 * Every row is checkable. The subject comes from a closed vocabulary, and the
 * quotes in the dropdown are spans the meaning layer verified appear in the
 * source review, so "Cleanliness — 3 reviews" can be opened and read rather
 * than taken on faith.
 *
 * Status is the merchant's. A refresh moves the evidence and counts forward but
 * never reopens or closes anything, which is what keeps avg_rating before and
 * after a resolution a fair comparison.
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
  open: "bg-coral/10 text-coral border-coral/25",
  in_progress: "bg-amber-50 text-amber-700 border-amber-200",
  done: "bg-emerald-50 text-emerald-700 border-emerald-200",
  dismissed: "bg-ink/[0.04] text-ink/45 border-ink/10",
};

function StatusPill({ status }: { status: LocationIssue["status"] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_STYLE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

/** One issue, expandable to the reviews and quotes behind it. */
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

  return (
    <div
      className={`rounded-xl border bg-white transition ${
        issue.status === "open" || issue.status === "in_progress"
          ? "border-ink/[0.08]"
          : "border-ink/[0.05] opacity-75"
      }`}
    >
      <div className="flex flex-wrap items-start gap-3 p-4">
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-start gap-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40"
        >
          <span
            aria-hidden
            className={`mt-0.5 shrink-0 text-ink/30 transition ${open ? "rotate-90" : ""}`}
          >
            ▸
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-[14px] font-semibold text-ink">
                {issue.subject_label}
              </span>
              <StatusPill status={issue.status} />
              {showLocation && issue.channel_name && (
                <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-medium text-ink/60">
                  {issue.channel_name}
                </span>
              )}
            </span>
            <span className="mt-1 block text-[12px] text-ink/55">
              {issue.negative_count} of {issue.review_count} review
              {issue.review_count === 1 ? "" : "s"} negative · avg{" "}
              {issue.avg_rating.toFixed(1)}★
            </span>
            {issue.title && (
              <span className="mt-1.5 block text-[12.5px] leading-5 text-ink">
                <span className="font-medium">Fix:</span> {issue.title}
              </span>
            )}
          </span>
        </button>

        <div className="flex shrink-0 items-center gap-1.5">
          {issue.status !== "done" && (
            <button
              onClick={() => onUpdate({ status: "done" })}
              disabled={updating}
              className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-40"
            >
              Mark fixed
            </button>
          )}
          {issue.status === "done" && (
            <button
              onClick={() => onUpdate({ status: "open" })}
              disabled={updating}
              className="rounded-lg border border-ink/10 px-2.5 py-1.5 text-[11px] font-medium text-ink/55 transition hover:bg-ink/[0.04] disabled:opacity-40"
            >
              Reopen
            </button>
          )}
          {issue.status === "open" && (
            <button
              onClick={() => onUpdate({ status: "dismissed" })}
              disabled={updating}
              title="Not a real problem — record that decision separately from fixing it"
              className="rounded-lg px-2.5 py-1.5 text-[11px] text-ink/35 transition hover:text-ink/60 hover:bg-ink/[0.03] disabled:opacity-40"
            >
              Not a problem
            </button>
          )}
        </div>
      </div>

      {open && (
        <div className="border-t border-ink/[0.06] px-4 py-3.5">
          {issue.detail && (
            <p className="text-[12px] leading-5 text-ink/65">{issue.detail}</p>
          )}

          <p className="mt-3 text-[10px] font-bold uppercase tracking-wide text-ink/40">
            What customers actually said
          </p>
          {issue.evidence.length === 0 ? (
            <p className="mt-1 text-[12px] text-ink/45">
              No verbatim quotes were captured for this one.
            </p>
          ) : (
            <ul className="mt-1.5 space-y-1.5">
              {issue.evidence.map((e, i) => (
                <li
                  key={`${e.review_id}-${i}`}
                  className="flex flex-wrap items-baseline gap-2 rounded-lg bg-ink/[0.02] px-2.5 py-1.5"
                >
                  <span className="text-[12px] leading-5 text-ink" dir="auto">
                    “{e.quote}”
                  </span>
                  <span className="text-[10px] font-semibold text-ink/35">
                    {e.rating}★
                  </span>
                </li>
              ))}
            </ul>
          )}

          <label className="mt-3 block">
            <span className="text-[11px] font-semibold text-ink/60">
              What you did about it
            </span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={2000}
              placeholder="Deep clean booked for Monday, contractor confirmed…"
              className="mt-1 w-full resize-y rounded-lg border border-ink/10 bg-white px-2.5 py-2 text-[12.5px] leading-5 text-ink outline-none focus:border-deep-violet/50"
            />
          </label>
          <div className="mt-1.5 flex items-center gap-2">
            <button
              onClick={saveNote}
              disabled={savingNote}
              className="rounded-lg bg-ink px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-ink/90 disabled:opacity-40"
            >
              {savingNote ? "Saving…" : "Save note"}
            </button>
            {issue.resolved_at && (
              <span className="text-[11px] text-ink/40">
                Resolved{" "}
                {new Date(issue.resolved_at).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function IssuesContent() {
  const [issues, setIssues] = useState<LocationIssue[]>([]);
  const [heldOut, setHeldOut] = useState({ total: 0, reviewable: 0, reviews: 0 });
  const [channels, setChannels] = useState<{ id: string; name: string }[]>([]);
  const [channel, setChannel] = useState<string>("");
  // Which scope has finished loading, rather than a boolean flipped inside the
  // effect. Keeps the skeleton up on a scope change without a render cascade,
  // and avoids hiding rows that are still valid for the previous scope.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    // Same source the reviews page uses, so the two filters agree on which
    // locations exist and what they are called.
    apiFetch("/api/v1/channels/?limit=100")
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
      setError(
        e instanceof Error ? e.message : "Could not load issues."
      );
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
      // Reorder locally so a status change is reflected immediately; the
      // grouped sections below are derived from this list.
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

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Issues</h1>
          <p className="mt-0.5 text-[13px] text-ink/55">
            What customers complained about, and what to do about it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            aria-label="Location"
            className="rounded-lg border border-ink/10 bg-white px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-deep-violet/50"
          >
            <option value="">All locations</option>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            onClick={doRefresh}
            disabled={refreshing}
            className="rounded-lg bg-deep-violet px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
          >
            {refreshing ? "Checking…" : "Re-check reviews"}
          </button>
        </div>
      </div>

      {note && (
        <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-[12px] text-emerald-800">
          {note}
        </p>
      )}
      {error && (
        <p className="mt-3 rounded-lg bg-coral/10 px-3 py-2 text-[12px] text-coral">
          {error}
        </p>
      )}

      {heldOut.total > 0 && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
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
        <div className="mt-4 space-y-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-xl bg-ink/[0.04]"
              aria-hidden
            />
          ))}
        </div>
      ) : issues.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-ink/10 bg-white/60 p-8 text-center">
          <p className="text-[14px] font-semibold text-ink">No issues found</p>
          <p className="mx-auto mt-1 max-w-sm text-[12.5px] leading-5 text-ink/50">
            Issues appear when negative reviews name something specific. If you
            just connected a location, re-check after the first sync.
          </p>
        </div>
      ) : (
        <>
          {STATUS_ORDER.filter((s) => s !== "dismissed").map((status) => {
            const group = grouped[status] ?? [];
            if (group.length === 0) return null;
            return (
              <section key={status} className="mt-5">
                <h2 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-ink/40">
                  {STATUS_LABEL[status]}
                  <span className="ml-1.5 font-semibold text-ink/30">
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
            <details className="mt-5">
              <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-wide text-ink/40">
                Not a problem{" "}
                <span className="font-semibold text-ink/30">
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
  );
}

export default function IssuesPage() {
  return (
    <IssuesContent />
  );
}
