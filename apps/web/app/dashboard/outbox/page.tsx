"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";
import LogoLoader from "@/components/LogoLoader";
import { apiFetch } from "@/lib/api-rag";
import {
  approveReply,
  rejectReply,
  retryReply,
  verifyPostedReplies,
  type ReviewReplyDTO,
  type ReviewInsight,
} from "@/lib/api-analytics";

interface ChannelOption {
  id: string;
  display_name: string | null;
}

type StatusFilter = "pending_approval" | "posted" | "failed";

const ALL_BRANCHES = "__all__";

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function initialsOf(name: string | null): string {
  const parts = (name ?? "Anonymous").trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return (parts[0]?.slice(0, 2) ?? "A").toUpperCase();
}

const STATUS_META: Record<StatusFilter, { label: string; pill: string }> = {
  pending_approval: {
    label: "Pending",
    pill: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  posted: {
    label: "Posted",
    pill: "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300",
  },
  failed: {
    label: "Failed",
    pill: "bg-red-500/15 text-red-600 dark:text-red-400",
  },
};

function apiDetail(e: unknown): string {
  if (e instanceof Error) {
    try {
      const parsed = JSON.parse(e.message) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch {
      /* not JSON */
    }
  }
  return "";
}

/** Shared pager — shown only when a tab overflows one page. */
function Pager({ page, totalPages, onPage }: {
  page: number;
  totalPages: number;
  onPage: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-3 pt-1">
      <button
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
        className="rounded-lg bg-ink/[0.04] px-3 py-1.5 text-[11px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.07] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-40 dark:bg-fog/[0.06] dark:text-fog/60"
      >
        ← Prev
      </button>
      <span className="text-[11px] font-medium tabular-nums text-ink/45 dark:text-fog/45">
        Page {page} of {totalPages}
      </span>
      <button
        onClick={() => onPage(page + 1)}
        disabled={page >= totalPages}
        className="rounded-lg bg-ink/[0.04] px-3 py-1.5 text-[11px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.07] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-40 dark:bg-fog/[0.06] dark:text-fog/60"
      >
        Next →
      </button>
    </div>
  );
}

/** Posted reply as a conversation: customer review → your live response. */
/** Google "G" in official colors. */
function GoogleG({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
    </svg>
  );
}

/** Posted reply: collapsed row (profile + stars + time + branch), expands to review + response. */
function PostedCard({ r, branchName, showBranch }: {
  r: ReviewReplyDTO;
  branchName: string;
  showBranch: boolean;
}) {
  const [open, setOpen] = useState(false);
  const reviewUrl = (r as ReviewReplyDTO & { review_url?: string }).review_url;
  return (
    <article className="overflow-hidden rounded-2xl border border-ink/[0.06] bg-white shadow-sm dark:border-fog/[0.06] dark:bg-ink">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 p-3.5 text-left outline-none transition hover:bg-ink/[0.015] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-deep-violet/40 dark:hover:bg-fog/[0.02]"
      >
        <GoogleG className="h-5 w-5 shrink-0" />
        <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet">
          {initialsOf(r.reviewer_name)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="truncate text-[13px] font-bold text-ink dark:text-fog">
              {r.reviewer_name ?? "Anonymous"}
            </span>
            <span aria-label={`${r.rating} out of 5 stars`} className="font-bold text-amber-600">
              {"★".repeat(Math.max(0, Math.min(5, r.rating)))}
            </span>
          </span>
          <span className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-ink/40 dark:text-fog/40">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3 w-3 shrink-0 text-emerald-600" aria-hidden>
              <path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-4h6v4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="truncate">{[showBranch ? branchName : null, timeAgo(r.created_at)].filter(Boolean).join(" · ")}</span>
          </span>
        </span>
        <span className="hidden shrink-0 items-center gap-1 rounded-full bg-emerald-600/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 sm:inline-flex dark:text-emerald-300">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Live
        </span>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-3.5 w-3.5 shrink-0 text-ink/30 transition-transform dark:text-fog/30 ${open ? "rotate-180" : ""}`} aria-hidden>
          <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-ink/[0.06] px-4 pb-4 pt-3 dark:border-fog/[0.06]">
          {r.review_text && (
            <blockquote className="rounded-r-xl border-l-[3px] border-ink/15 bg-ink/[0.025] py-2.5 pl-3 pr-2 dark:border-fog/15 dark:bg-fog/[0.04]">
              <p className="text-[13px] italic leading-6 text-ink/70 dark:text-fog/70">“{r.review_text}”</p>
            </blockquote>
          )}

          <div className="mt-3 rounded-xl border border-emerald-600/15 bg-emerald-600/[0.05] p-3 dark:bg-emerald-500/[0.06]">
            <p className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-emerald-700/70 dark:text-emerald-300/70">
              Your reply — live on Google
            </p>
            <p className="whitespace-pre-wrap text-[13px] leading-6 text-ink/85 dark:text-fog/85">
              {r.reply_text || "—"}
            </p>
          </div>

          {reviewUrl && (
            <div className="mt-2.5 flex justify-end">
              <a
                href={reviewUrl}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-deep-violet underline-offset-2 transition hover:underline"
              >
                View on Google
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-2.5 w-2.5" aria-hidden>
                  <path d="M7 17L17 7M9 7h8v8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

type OutboxTab = "pending" | "posted" | "failed" | "flagged";

export default function OutboxPage() {
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<OutboxTab>("pending");
  const [replies, setReplies] = useState<ReviewReplyDTO[]>([]);
  const [flagged, setFlagged] = useState<ReviewInsight[]>([]);
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  const scopeIds = useCallback(
    (scope: string | null, list: ChannelOption[]) => {
      if (!scope || scope === ALL_BRANCHES) return list.map((c) => c.id);
      return [scope];
    },
    []
  );

  // One load for the whole page: replies + flagged across the branch scope.
  const loadScope = useCallback(async (scope: string | null, list: ChannelOption[]) => {
    setLoading(true);
    try {
      const ids = scope === ALL_BRANCHES || !scope
        ? list.map((c) => c.id)
        : [scope];
      const lists: ReviewReplyDTO[][] = await Promise.all(
        ids.map(async (id) => {
          try {
            const r = await apiFetch(`/api/v1/channels/${id}/reviews?limit=100`);
            return (r.replies ?? []) as ReviewReplyDTO[];
          } catch {
            return [];
          }
        })
      );
      // One row per review — newest draft wins.
      const seen = new Map<string, ReviewReplyDTO>();
      for (const d of lists.flat()) {
        const prev = seen.get(d.review_id);
        if (!prev || d.created_at > prev.created_at) seen.set(d.review_id, d);
      }
      const names: Record<string, string> = {};
      for (const c of list) names[c.id] = c.display_name || "Location";
      if (scope !== ALL_BRANCHES && scope) {
        try {
          const data = await apiFetch(`/api/v1/analytics/reviews/insights?channel_id=${encodeURIComponent(scope)}&status=skipped&limit=100`);
          setFlagged((data.items ?? []) as ReviewInsight[]);
        } catch {
          setFlagged([]);
        }
      } else {
        const flaggedLists: ReviewInsight[][] = await Promise.all(
          ids.map(async (id) => {
            try {
              const data = await apiFetch(`/api/v1/analytics/reviews/insights?channel_id=${encodeURIComponent(id)}&status=skipped&limit=100`);
              return (data.items ?? []) as ReviewInsight[];
            } catch {
              return [];
            }
          })
        );
        setFlagged(flaggedLists.flat());
      }
      setChannelNames(names);
      setReplies([...seen.values()].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)));
    } catch {
      setReplies([]);
      setFlagged([]);
      setBanner({ kind: "err", text: "Could not load the outbox." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        if (cancelled) return;
        const google = (data.channels ?? []).filter(
          (c: { platform: string }) => c.platform === "google_reviews"
        );
        setChannels(google);
        if (google.length > 0) {
          setSelected(ALL_BRANCHES);
          void loadScope(ALL_BRANCHES, google);
        } else {
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadScope]);

  const changeScope = (scope: string) => {
    setSelected(scope);
    setPage(1);
    void loadScope(scope, channels);
  };

  const counts = {
    pending: replies.filter((r) => r.status === "pending_approval").length,
    posted: replies.filter((r) => r.status === "posted").length,
    failed: replies.filter((r) => r.status === "failed").length,
    flagged: flagged.length,
  };
  const visible = replies.filter((r) =>
    tab === "pending" ? r.status === "pending_approval"
    : tab === "posted" ? r.status === "posted"
    : tab === "failed" ? r.status === "failed"
    : false
  );

  // Client-side paging over the already-loaded scope (100/channel cap).
  const sourceLen = tab === "flagged" ? flagged.length : visible.length;
  const totalPages = Math.max(1, Math.ceil(sourceLen / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedReplies = visible.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const pagedFlagged = flagged.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const reload = () => {
    if (selected) void loadScope(selected, channels);
  };

  const onRetry = async (r: ReviewReplyDTO) => {
    setBusy(r.id);
    setBanner(null);
    try {
      await retryReply(r.channel_id, r.id);
      setBanner({ kind: "ok", text: "Returned to the approval queue — approve it when ready." });
      reload();
    } catch (e) {
      setBanner({ kind: "err", text: apiDetail(e) || "Retry failed. Try again." });
    } finally {
      setBusy(null);
    }
  };

  const onApprove = async (r: ReviewReplyDTO) => {
    setBusy(r.id);
    setBanner(null);
    try {
      await approveReply(r.channel_id, r.id);
      setBanner({ kind: "ok", text: "Published to Google — verified live." });
      reload();
    } catch (e) {
      setBanner({ kind: "err", text: apiDetail(e) || "Could not publish. Try again." });
    } finally {
      setBusy(null);
    }
  };

  const onVerifyPosted = async () => {
    if (!selected || busy !== null) return;
    setBusy("verify");
    setBanner(null);
    try {
      const ids = scopeIds(selected, channels);
      let checked = 0, confirmed = 0, corrected = 0, skipped = 0;
      for (const id of ids) {
        try {
          const res = await verifyPostedReplies(id) as {
            checked: number;
            confirmed: number;
            corrected: number;
            skipped_localith?: number;
          };
          checked += res.checked;
          confirmed += res.confirmed;
          corrected += res.corrected;
          skipped += res.skipped_localith ?? 0;
        } catch {
          /* one branch failing must not block the others */
        }
      }
      let text: string;
      if (checked === 0 && skipped > 0) {
        text = `${skipped} Localith-published ${skipped === 1 ? "reply" : "replies"} — confirmed at publish time, nothing to re-check.`;
      } else if (checked === 0) {
        text = "Nothing to verify right now.";
      } else if (corrected > 0) {
        text = `${corrected} of ${checked} were not actually on Google — moved back to Failed.`;
      } else {
        text = `All ${confirmed} confirmed live on Google.`;
      }
      setBanner({
        kind: corrected > 0 ? "err" : "ok",
        text,
      });
      reload();
    } catch (e) {
      setBanner({ kind: "err", text: apiDetail(e) || "Could not verify. Try again." });
    } finally {
      setBusy(null);
    }
  };

  const onDiscard = async (r: ReviewReplyDTO) => {
    setBusy(r.id);
    setBanner(null);
    try {
      await rejectReply(r.channel_id, r.id);
      reload();
    } catch {
      setBanner({ kind: "err", text: "Could not discard." });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Breadcrumbs items={[{ label: "Outbox" }]} />
          <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Outbox</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            Every reply the engine wrote — pending, posted, and failed ones you can retry.
          </p>
        </div>
        {channels.length > 0 && (
          <div className="relative">
            <select
              value={selected ?? ""}
              onChange={(e) => changeScope(e.target.value)}
              className="w-56 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value={ALL_BRANCHES}>All branches ({channels.length})</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name || "Location"}
                </option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40 dark:text-fog/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </div>
        )}
      </div>

      {banner && (
        <div
          role="status"
          className={`rounded-xl border p-3 text-[13px] ${
            banner.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <span>{banner.text}</span>
            <button
              onClick={() => setBanner(null)}
              className="shrink-0 text-[12px] underline underline-offset-2"
            >
              dismiss
            </button>
          </div>
        </div>
      )}

      {/* One tab bar — each tab owns its count, no cross-filter matrix */}
      <div className="flex rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.06]">
        {([
          { key: "pending", label: `Pending (${counts.pending})` },
          { key: "posted", label: `Posted (${counts.posted})` },
          { key: "failed", label: `Failed (${counts.failed})` },
          { key: "flagged", label: `Flagged (${counts.flagged})` },
        ] as { key: OutboxTab; label: string }[]).map((t) => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setPage(1); }}
            aria-pressed={tab === t.key}
            className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
              tab === t.key
                ? "bg-white text-deep-violet shadow-sm dark:bg-ink"
                : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "posted" && counts.posted > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-ink/[0.06] bg-white px-4 py-3 dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[12px] text-ink/55 dark:text-fog/55">
            Posted means confirmed live on Google. Re-check any time.
          </p>
          <button
            onClick={() => void onVerifyPosted()}
            disabled={busy !== null || !selected}
            className="shrink-0 rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
          >
            {busy === "verify" ? "Verifying…" : "Verify against Google"}
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <LogoLoader size={28} />
        </div>
      ) : channels.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-ink/[0.06] bg-white py-14 text-center dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[14px] font-semibold text-ink/70 dark:text-fog/70">No locations yet</p>
          <p className="max-w-sm text-[12px] text-ink/45 dark:text-fog/45">
            Connect your Google Business Profile and the engine will start drafting replies here.
          </p>
          <Link
            href="/dashboard/channels"
            className="rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90"
          >
            Connect
          </Link>
        </div>
      ) : tab === "flagged" ? (
        flagged.length === 0 ? (
          <div className="rounded-xl border border-ink/[0.06] bg-white py-12 text-center text-[13px] text-ink/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog/40">
            No reviews flagged as unavailable yet.
          </div>
        ) : (
          <>
          <div className="space-y-3">
            {pagedFlagged.map((r) => (
              <div
                key={r.id}
                className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
              >
                <div className="flex items-center gap-1.5 text-[11px] text-ink/50 dark:text-fog/50">
                  <span aria-label={`${r.rating} out of 5 stars`} className="font-bold text-amber-600">
                    {"★".repeat(Math.max(0, Math.min(5, r.rating)))}
                  </span>
                  <span className="truncate font-semibold text-ink dark:text-fog">
                    {r.reviewer_name ?? "Anonymous"}
                  </span>
                  <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-gray-600 dark:bg-fog/[0.06] dark:text-fog/50">
                    Unavailable
                  </span>
                </div>
                {r.review_text && (
                  <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">
                    “{r.review_text}”
                  </p>
                )}
                <p className="mt-1.5 text-[11px] text-ink/45">
                  Reviewer deleted this review or Google removed it — no reply is possible.
                </p>
              </div>
            ))}
          </div>
          <Pager page={safePage} totalPages={totalPages} onPage={setPage} />
          </>
        )
      ) : visible.length === 0 ? (
        <div className="rounded-xl border border-ink/[0.06] bg-white py-12 text-center text-[13px] text-ink/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog/40">
          {tab === "pending" && "Nothing waiting — new AI drafts will appear here."}
          {tab === "posted" && "No posted replies yet — approved replies show here with the live response."}
          {tab === "failed" && "Nothing failed — everything published cleanly."}
        </div>
      ) : tab === "posted" ? (
        <>
        <div className="space-y-4">
          {pagedReplies.map((r) => (
            <PostedCard
              key={r.id}
              r={r}
              branchName={channelNames[r.channel_id] ?? "Location"}
              showBranch={selected === ALL_BRANCHES}
            />
          ))}
          <Pager page={safePage} totalPages={totalPages} onPage={setPage} />
        </div>
        </>
      ) : (
        <div className="space-y-3">
          {pagedReplies.map((r) => {
            const reviewUrl = (r as ReviewReplyDTO & { review_url?: string }).review_url;
            return (
            <div
              key={r.id}
              className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
            >
              <div className="flex items-center gap-1.5 text-[11px] text-ink/50 dark:text-fog/50">
                <span aria-label={`${r.rating} out of 5 stars`} className="font-bold text-amber-600">
                  {"★".repeat(Math.max(0, Math.min(5, r.rating)))}
                </span>
                <span className="truncate font-semibold text-ink dark:text-fog">
                  {r.reviewer_name ?? "Anonymous"}
                </span>
                {reviewUrl && (
                  <a
                    href={reviewUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex shrink-0 items-center gap-0.5 text-[10px] font-semibold text-deep-violet underline-offset-2 transition hover:underline"
                  >
                    View on Google
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-2.5 w-2.5" aria-hidden>
                      <path d="M7 17L17 7M9 7h8v8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </a>
                )}
                <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_META[r.status as StatusFilter]?.pill ?? ""}`}>
                  {STATUS_META[r.status as StatusFilter]?.label ?? r.status}
                </span>
              </div>
              {r.review_text && (
                <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">
                  “{r.review_text}”
                </p>
              )}
              <div className="mt-2 rounded-lg bg-ink/[0.03] p-2.5 dark:bg-fog/[0.04]">
                <p className="text-[9px] font-bold uppercase tracking-wide text-ink/40">AI draft</p>
                <p className="mt-0.5 text-[12px] leading-relaxed text-ink/70 dark:text-fog/70">
                  {r.reply_text || "—"}
                </p>
              </div>
              {r.error && (
                <p className="mt-1.5 rounded-lg bg-coral/10 px-2.5 py-1.5 text-[11px] font-medium leading-relaxed text-coral">
                  {r.error}
                </p>
              )}
              <div className="mt-2 flex items-center justify-end gap-2">
                {r.status === "failed" && (
                  <>
                    <button
                      onClick={() => void onDiscard(r)}
                      disabled={busy !== null}
                      className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:bg-ink/[0.04] dark:text-fog/50 disabled:opacity-50"
                    >
                      Discard
                    </button>
                    <button
                      onClick={() => void onRetry(r)}
                      disabled={busy !== null}
                      className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                    >
                      {busy === r.id ? "Retrying…" : "Retry"}
                    </button>
                  </>
                )}
                {r.status === "pending_approval" && (
                  <>
                    <button
                      onClick={() => void onDiscard(r)}
                      disabled={busy !== null}
                      className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:bg-ink/[0.04] dark:text-fog/50 disabled:opacity-50"
                    >
                      Discard
                    </button>
                    <button
                      onClick={() => void onApprove(r)}
                      disabled={busy !== null}
                      className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                    >
                      {busy === r.id ? "Approving…" : "Approve"}
                    </button>
                  </>
                )}
              </div>
            </div>
            );
          })}
          <Pager page={safePage} totalPages={totalPages} onPage={setPage} />
        </div>
      )}
    </div>
  );
}
