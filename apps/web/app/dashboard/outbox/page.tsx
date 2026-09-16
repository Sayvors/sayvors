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

export default function OutboxPage() {
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [outboxTab, setOutboxTab] = useState<"replies" | "flagged">("replies");
  const [filter, setFilter] = useState<StatusFilter>("pending_approval");
  const [replies, setReplies] = useState<ReviewReplyDTO[]>([]);
  const [flagged, setFlagged] = useState<ReviewInsight[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = useCallback(async (channelId: string) => {
    setLoading(true);
    try {
      const r = await apiFetch(`/api/v1/channels/${channelId}/reviews?limit=100`);
      setReplies((r.replies ?? []) as ReviewReplyDTO[]);
    } catch {
      setReplies([]);
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
          setSelected(google[0].id);
          void load(google[0].id);
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
  }, [load]);

  const loadFlagged = useCallback(async (channelId: string) => {
    try {
      const data = await apiFetch(
        `/api/v1/analytics/reviews/insights?channel_id=${encodeURIComponent(channelId)}&status=skipped&limit=100`
      );
      setReplies([]);
      setFlagged((data.items ?? []) as ReviewInsight[]);
    } catch {
      setFlagged([]);
    }
  }, []);

  const visible = replies.filter((r) => r.status === filter);

  const handleTabChange = async (tab: "replies" | "flagged") => {
    setOutboxTab(tab);
    if (!selected) return;
    if (tab === "flagged") {
      await loadFlagged(selected);
    } else {
      await load(selected);
    }
  };

  const onRetry = async (r: ReviewReplyDTO) => {
    setBusy(r.id);
    setBanner(null);
    try {
      await retryReply(r.channel_id, r.id);
      setBanner({ kind: "ok", text: "Returned to the approval queue — approve it when ready." });
      if (selected) void load(selected);
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
      if (selected) void load(selected);
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
      const res = await verifyPostedReplies(selected) as {
        checked: number;
        confirmed: number;
        corrected: number;
        skipped_localith?: number;
      };
      const skipped = res.skipped_localith ?? 0;
      let text: string;
      if (res.checked === 0 && skipped > 0) {
        text = `${skipped} Localith-published ${skipped === 1 ? "reply" : "replies"} skipped — ${skipped === 1 ? "it is" : "they are"} confirmed at publish time. Only Google-connected replies can be re-checked.`;
      } else if (res.checked === 0) {
        text = "Nothing marked posted to check.";
      } else if (res.corrected > 0) {
        text = `${res.corrected} of ${res.checked} were not actually on Google — moved back to Failed.`;
      } else {
        text = `All ${res.confirmed} confirmed live on Google.`;
      }
      setBanner({
        kind: res.corrected > 0 ? "err" : "ok",
        text,
      });
       void (outboxTab === "flagged" ? (selected ? loadFlagged(selected) : Promise.resolve()) : load(selected));
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
      if (selected) void load(selected);
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
              onChange={(e) => {
                setSelected(e.target.value);
                if (e.target.value) void load(e.target.value);
              }}
              className="w-56 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
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

      {/* Status filter */}
      <div className="flex rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.06]">
        {(Object.keys(STATUS_META) as StatusFilter[]).map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            aria-pressed={filter === s}
            className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
              filter === s
                ? "bg-white text-deep-violet shadow-sm dark:bg-ink"
                : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
            }`}
          >
            {STATUS_META[s].label}
          </button>
        ))}
      </div>

      {/* View toggle: Outbox / Flagged */}
      <div className="flex rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.06]">
        <button
          onClick={() => handleTabChange("replies")}
          className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
            outboxTab === "replies"
              ? "bg-white text-deep-violet shadow-sm dark:bg-ink"
              : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
          }`}
        >
          Outbox
        </button>
        <button
          onClick={() => handleTabChange("flagged")}
          className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
            outboxTab === "flagged"
              ? "bg-white text-deep-violet shadow-sm dark:bg-ink"
              : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
          }`}
        >
          Flagged
        </button>
      </div>

      {filter === "posted" && (
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
      ) : outboxTab === "flagged" ? (
        flagged.length === 0 ? (
          <div className="rounded-xl border border-ink/[0.06] bg-white py-12 text-center text-[13px] text-ink/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog/40">
            No reviews flagged as unavailable yet.
          </div>
        ) : (
          <div className="space-y-3">
            {flagged.map((r) => (
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
        )
      ) : visible.length === 0 ? (
        <div className="rounded-xl border border-ink/[0.06] bg-white py-12 text-center text-[13px] text-ink/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog/40">
          No {STATUS_META[filter].label.toLowerCase()} replies for this location.
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((r) => {
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
        </div>
      )}
    </div>
  );
}
