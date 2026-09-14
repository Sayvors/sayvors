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
  type ReviewReplyDTO,
} from "@/lib/api-analytics";

interface ChannelOption {
  id: string;
  display_name: string | null;
}

type StatusFilter = "pending_approval" | "posted" | "failed" | "approved";

const STATUS_META: Record<StatusFilter, { label: string; pill: string }> = {
  pending_approval: {
    label: "Pending",
    pill: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  posted: {
    label: "Posted",
    pill: "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300",
  },
  approved: {
    label: "Approved",
    pill: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
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
  const [filter, setFilter] = useState<StatusFilter>("pending_approval");
  const [replies, setReplies] = useState<ReviewReplyDTO[]>([]);
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

  const visible = replies.filter((r) => r.status === filter);

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
      const updated = await approveReply(r.channel_id, r.id);
      setBanner({
        kind: "ok",
        text:
          updated.status === "approved"
            ? "Approved — post it from your Localith dashboard to make it live on Google."
            : "Published to Google.",
      });
      if (selected) void load(selected);
    } catch (e) {
      setBanner({ kind: "err", text: apiDetail(e) || "Could not publish. Try again." });
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

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <LogoLoader size={28} />
        </div>
      ) : channels.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-ink/[0.06] bg-white py-14 text-center dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[14px] font-semibold text-ink/70 dark:text-fog/70">No locations yet</p>
          <p className="max-w-sm text-[12px] text-ink/45 dark:text-fog/45">
            Connect your Localith listing and the engine will start drafting replies here.
          </p>
          <Link
            href="/dashboard/channels"
            className="rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90"
          >
            Connect
          </Link>
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-xl border border-ink/[0.06] bg-white py-12 text-center text-[13px] text-ink/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog/40">
          No {STATUS_META[filter].label.toLowerCase()} replies for this location.
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((r) => (
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
                  <button
                    onClick={() => void onRetry(r)}
                    disabled={busy !== null}
                    className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                  >
                    {busy === r.id ? "Retrying…" : "Retry"}
                  </button>
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
          ))}
        </div>
      )}
    </div>
  );
}
