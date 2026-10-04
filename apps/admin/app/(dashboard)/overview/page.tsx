"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import type { AdminOverview } from "@/lib/admin-api";

// ─── helpers ───────────────────────────────────────────────────────────────
function fmtNum(n: number): string {
  return n.toLocaleString("en-US");
}
function pct(part: number, whole: number): number {
  if (!whole || whole <= 0) return 0;
  return Math.round((part / whole) * 100);
}
function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}
function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return d.toLocaleDateString();
}

const STATUS_DOT: Record<string, string> = {
  published: "bg-emerald-500",
  scheduled: "bg-sky-500",
  draft: "bg-amber-400",
  pending: "bg-violet-500",
  failed: "bg-red-500",
  archived: "bg-ink/20",
};

// ─── count-up ──────────────────────────────────────────────────────────────
// Animates once on first paint; renders the final value immediately for
// reduced-motion users and always exposes it to assistive tech.
function useCountUp(target: number, decimals = 0, duration = 900): string {
  const reduceMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [frame, setFrame] = useState(reduceMotion ? 1 : 0);
  useEffect(() => {
    if (reduceMotion) return;
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      setFrame(1 - Math.pow(1 - p, 3));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration, reduceMotion]);
  const shown = target * frame;
  return decimals > 0
    ? shown.toFixed(decimals)
    : Math.round(shown).toLocaleString("en-US");
}

function HeroNumeral({ value, decimals = 0, dark = false }: { value: number; decimals?: number; dark?: boolean }) {
  const text = useCountUp(value, decimals);
  return (
    <span className={`font-bold tabular-nums tracking-tight ${dark ? "text-white" : "text-ink"}`}>
      {text}
    </span>
  );
}

// ─── skeleton ──────────────────────────────────────────────────────────────
function SkeletonOverview() {
  return (
    <div className="space-y-5" aria-hidden aria-label="Loading overview">
      <div className="h-10 w-64 animate-pulse rounded-[6px] bg-white/60" />
      <div className="h-24 animate-pulse rounded-[6px] bg-white/60" />
      <div className="h-52 animate-pulse rounded-[6px] bg-ink/10" />
      <div className="grid gap-3 lg:grid-cols-5">
        <div className="h-56 animate-pulse rounded-[6px] bg-white/60 lg:col-span-3" />
        <div className="h-56 animate-pulse rounded-[6px] bg-white/60 lg:col-span-2" />
      </div>
    </div>
  );
}

// ─── main ──────────────────────────────────────────────────────────────────
export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [barsIn, setBarsIn] = useState(false);

  const fetchData = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true);
    try {
      const o = await adminFetch<AdminOverview>("/api/v1/admin/overview");
      setData(o);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    } finally {
      if (isRefresh) setRefreshing(false);
      else setLoading(false);
    }
  }, []);

  // Initial load: promise callbacks only, no synchronous setState in the body.
  useEffect(() => {
    let cancelled = false;
    adminFetch<AdminOverview>("/api/v1/admin/overview")
      .then((o) => {
        if (cancelled) return;
        setData(o);
        setUpdatedAt(new Date());
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Load failed.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Funnel bars draw in after first paint.
  useEffect(() => {
    let raf = 0;
    raf = requestAnimationFrame(() => {
      raf = requestAnimationFrame(() => setBarsIn(true));
    });
    return () => cancelAnimationFrame(raf);
  }, []);

  if (loading && !data) {
    return <SkeletonOverview />;
  }

  if ((error && !data) || !data) {
    return (
      <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
        <p className="text-[14px] font-bold text-ink">Couldn&apos;t load overview.</p>
        {error && <p className="mt-1 text-[12px] text-ink/50">{error}</p>}
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            void fetchData(false).finally(() => setLoading(false));
          }}
          className="btn-primary mt-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
        >
          Retry
        </button>
      </div>
    );
  }

  const total = data.users_total || 0;
  const verifiedRate = pct(data.users_verified, total);
  const connectionRate = pct(data.connections, total);
  const connectionRateVerified = pct(data.connections, data.users_verified || 0);
  const problems = data.outbox_failed + data.ingest_failed;
  const isHealthy = problems === 0 && data.outbox_pending < 25;
  const isDegraded = problems > 0;
  const avgReviews = total ? data.reviews_total / total : 0;
  const avgPosts = total ? data.posts_total / total : 0;
  const docsPerBank = data.databanks_total ? data.documents_total / data.databanks_total : 0;
  const newShare = pct(data.signups_last_7d, total);
  const postsEntries = Object.entries(data.posts_by_status).sort((a, b) => b[1] - a[1]);
  const postsTotal = postsEntries.reduce((s, [, v]) => s + v, 0) || data.posts_total || 1;
  const topPost: [string, number] | null = postsEntries[0] ?? null;

  const verdict = isHealthy ? "healthy" : isDegraded ? "needs attention" : "watch";

  return (
    <div className="space-y-5">
      {/* ── masthead ─────────────────────────────────────────── */}
      <div className="admin-rise flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink/40">
            Sayvors · Admin
          </p>
          <h1 className="mt-1 flex flex-wrap items-center gap-2.5 text-[22px] font-bold tracking-tight text-ink">
            Platform overview
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest ${
                isHealthy
                  ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                  : isDegraded
                    ? "bg-red-50 text-red-700 ring-1 ring-red-200"
                    : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
              }`}
            >
              <span
                aria-hidden
                className={`h-1.5 w-1.5 rounded-full ${isHealthy ? "bg-emerald-500" : isDegraded ? "bg-red-500" : "bg-amber-500"}`}
              />
              {verdict}
            </span>
          </h1>
          <p className="mt-1 text-[11px] text-ink/40">
            {data.last_synced_at
              ? `Last listing sync ${fmtRelative(data.last_synced_at)}`
              : "No listing sync yet"}
            {updatedAt && <span> · Updated {updatedAt.toLocaleTimeString()} · read-only</span>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href="/tenants"
            className="hidden rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet sm:inline-flex"
          >
            View tenants →
          </Link>
          <button
            onClick={() => void fetchData(true)}
            disabled={refreshing}
            aria-busy={refreshing}
            className="inline-flex items-center gap-2 rounded-xl bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-[#4a2575] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
          >
            <svg
              aria-hidden
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              className={refreshing ? "animate-spin" : ""}
            >
              <path d="M21 12a9 9 0 1 1-2.64-6.36" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              <path d="M21 3v6h-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {/* ── the lede: the platform in one sentence ───────────── */}
      <p
        className="admin-rise max-w-[720px] text-[17px] font-medium leading-relaxed text-ink sm:text-[19px]"
        style={{ animationDelay: "70ms" }}
      >
        {total === 0 ? (
          <>No tenants yet — connect the first listing and this page starts telling the story.</>
        ) : (
          <>
            <b className="font-bold text-deep-violet">{fmtNum(total)} tenants</b>,{" "}
            <b className="font-bold text-deep-violet">{fmtNum(data.users_verified)} verified</b>,{" "}
            <b className="font-bold text-deep-violet">{fmtNum(data.connections)} connected</b>
            {" — "}
            {fmtNum(data.reviews_total)} reviews and {fmtNum(data.posts_total)} posts indexed.{" "}
            {isHealthy ? (
              <span className="text-ink/60">Pipeline healthy.</span>
            ) : isDegraded ? (
              <span className="font-semibold text-red-700">
                {problems} item{problems > 1 ? "s need" : " needs"} attention.
              </span>
            ) : (
              <span className="text-ink/60">Queue is building — keep an eye on it.</span>
            )}
          </>
        )}
      </p>

      {/* ── funnel: acquisition → verification → activation ──── */}
      <section
        aria-labelledby="funnel-heading"
        className="admin-rise overflow-hidden rounded-[6px] bg-[#15102e] p-5 sm:p-6"
        style={{ animationDelay: "140ms" }}
      >
        <h2 id="funnel-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-white/40">
          Tenant funnel
        </h2>
        <div className="mt-4 grid items-stretch gap-5 sm:grid-cols-[1fr_auto_1fr_auto_1fr] sm:gap-3">
          {/* stage 1 */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">1 · Acquisition</p>
            <p className="mt-1 text-[44px] font-bold tabular-nums leading-none sm:text-[52px]">
              <HeroNumeral value={total} dark />
            </p>
            <p className="mt-1.5 text-[12px] font-semibold text-white">tenants</p>
            <p className="mt-0.5 text-[11px] text-white/45">
              {data.signups_last_7d > 0 ? (
                <>+{fmtNum(data.signups_last_7d)} in 7 days · {newShare}% of base</>
              ) : (
                "no sign-ups in 7 days"
              )}
            </p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-violet-soft transition-[width] duration-700 ease-out"
                style={{ width: barsIn && total > 0 ? "100%" : "0%" }}
              />
            </div>
          </div>
          {/* connector */}
          <div className="flex items-center justify-center" aria-hidden>
            <div className="text-center">
              <p className="text-[18px] font-bold tabular-nums text-violet-soft">{total > 0 ? `${verifiedRate}%` : "—"}</p>
              <p className="text-[10px] font-bold uppercase tracking-widest text-white/35">
                <span className="sm:hidden">↓ verify</span>
                <span className="hidden sm:inline">→ verify</span>
              </p>
            </div>
          </div>
          {/* stage 2 */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">2 · Verification</p>
            <p className="mt-1 text-[44px] font-bold tabular-nums leading-none sm:text-[52px]">
              <HeroNumeral value={data.users_verified} dark />
            </p>
            <p className="mt-1.5 text-[12px] font-semibold text-white">verified</p>
            <p className="mt-0.5 text-[11px] text-white/45">
              {total > 0 ? `${verifiedRate}% of tenants` : "nothing to verify yet"}
            </p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-violet-soft transition-[width] duration-700 ease-out"
                style={{ width: barsIn ? `${Math.max(total > 0 ? 4 : 0, verifiedRate)}%` : "0%" }}
              />
            </div>
          </div>
          {/* connector */}
          <div className="flex items-center justify-center" aria-hidden>
            <div className="text-center">
              <p className="text-[18px] font-bold tabular-nums text-violet-soft">
                {data.users_verified > 0 ? `${connectionRateVerified}%` : "—"}
              </p>
              <p className="text-[10px] font-bold uppercase tracking-widest text-white/35">
                <span className="sm:hidden">↓ connect</span>
                <span className="hidden sm:inline">→ connect</span>
              </p>
            </div>
          </div>
          {/* stage 3 */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">3 · Activation</p>
            <p className="mt-1 text-[44px] font-bold tabular-nums leading-none sm:text-[52px]">
              <HeroNumeral value={data.connections} dark />
            </p>
            <p className="mt-1.5 text-[12px] font-semibold text-white">connected listings</p>
            <p className="mt-0.5 text-[11px] text-white/45">
              {data.users_verified > 0 ? (
                `${connectionRateVerified}% of verified`
              ) : (
                <span className="text-white/60">activation starts at verification</span>
              )}
            </p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-violet-soft transition-[width] duration-700 ease-out"
                style={{ width: barsIn ? `${Math.max(total > 0 ? 4 : 0, connectionRate)}%` : "0%" }}
              />
            </div>
          </div>
        </div>
      </section>

      {/* ── urgent first: problems ───────────────────────────── */}
      {problems > 0 && (
        <div
          role="alert"
          className="admin-rise flex flex-col gap-3 rounded-[6px] border border-red-200 bg-red-50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
          style={{ animationDelay: "200ms" }}
        >
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-red-600 text-white">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M12 9v6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <circle cx="12" cy="17" r="1" fill="currentColor" />
                <path d="M10.3 3.6L3 17a1 1 0 0 0 .9 1.4h14.2a1 1 0 0 0 .9-1.4L11.7 3.6a1 1 0 0 0-1.4 0z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
              </svg>
            </span>
            <div>
              <p className="text-[13px] font-bold leading-none text-red-800">
                {problems} failed item{problems > 1 ? "s" : ""} need attention
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-red-700/80">
                Outbox failed <b className="font-bold text-red-800">{fmtNum(data.outbox_failed)}</b> · Ingest
                failed <b className="font-bold text-red-800">{fmtNum(data.ingest_failed)}</b> · Pending{" "}
                {fmtNum(data.outbox_pending)} still in queue.
              </p>
            </div>
          </div>
          <Link
            href="/logs"
            className="shrink-0 self-start rounded-xl bg-red-600 px-3.5 py-2 text-center text-[12px] font-bold text-white transition hover:bg-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 sm:self-auto"
          >
            Open logs →
          </Link>
        </div>
      )}

      {/* ── content engine + operations ──────────────────────── */}
      <div className="grid gap-3 lg:grid-cols-5">
        <section
          aria-labelledby="content-heading"
          className="admin-rise rounded-[6px] border-2 border-white bg-white/85 p-5 lg:col-span-3"
          style={{ animationDelay: "210ms" }}
        >
          <h2 id="content-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
            Content engine
          </h2>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data.reviews_total} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">reviews indexed</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {avgReviews >= 10 ? avgReviews.toFixed(0) : avgReviews.toFixed(1)} / tenant
              </p>
            </div>
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data.posts_total} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">posts created</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {avgPosts >= 10 ? avgPosts.toFixed(0) : avgPosts.toFixed(1)} / tenant
              </p>
            </div>
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data.databanks_total} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">databanks</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {fmtNum(data.documents_total)} docs · {docsPerBank >= 10 ? docsPerBank.toFixed(0) : docsPerBank.toFixed(1)}/bank
              </p>
            </div>
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data.outbox_pending} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">queued to send</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {problems > 0 ? `${problems} failed` : "nothing failing"}
              </p>
            </div>
          </div>
          {postsEntries.length > 0 && topPost && (
            <div className="mt-5 border-t border-ink/[0.06] pt-4">
              <p className="text-[11px] font-semibold text-ink/60">
                Posting momentum — <span className="font-bold text-ink">{fmtNum(topPost[1])} {topPost[0]}</span>{" "}
                <span className="font-normal text-ink/40">({pct(topPost[1], postsTotal)}% of {fmtNum(postsTotal)})</span>
              </p>
              <div className="mt-2 space-y-1.5">
                {postsEntries.slice(0, 4).map(([status, count]) => (
                  <div key={status} className="flex items-center gap-2">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status] ?? "bg-ink/20"}`} aria-hidden />
                    <span className="w-20 shrink-0 text-[11px] font-medium capitalize text-ink/60">{status}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink/[0.06]">
                      <div
                        className="h-full rounded-full bg-deep-violet transition-[width] duration-700 ease-out"
                        style={{ width: barsIn ? `${Math.max(4, (count / postsTotal) * 100)}%` : "0%" }}
                      />
                    </div>
                    <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-ink/50">{fmtNum(count)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <p className="mt-4 border-t border-ink/[0.06] pt-3 text-[12px] leading-relaxed text-ink/60">
            {data.reviews_total === 0 && data.posts_total === 0 ? (
              <>No content yet — tenants need connected listings to sync reviews and create posts.</>
            ) : data.reviews_total === 0 ? (
              <>Posts exist but no reviews synced. Check listing connections.</>
            ) : data.posts_total === 0 ? (
              <>Reviews syncing but no posts created. Tenants may need onboarding.</>
            ) : (
              <>
                Every connected tenant averages{" "}
                <b className="font-bold text-ink">
                  {avgReviews >= 10 ? avgReviews.toFixed(0) : avgReviews.toFixed(1)} reviews
                </b>{" "}
                feeding replies and{" "}
                <b className="font-bold text-ink">
                  {avgPosts >= 10 ? avgPosts.toFixed(0) : avgPosts.toFixed(1)} posts
                </b>{" "}
                in the pipeline.
              </>
            )}
          </p>
        </section>

        <section
          aria-labelledby="ops-heading"
          className="admin-rise rounded-[6px] border-2 border-white bg-white/85 p-5 lg:col-span-2"
          style={{ animationDelay: "280ms" }}
        >
          <h2 id="ops-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
            Operations
          </h2>
          <dl className="mt-3 space-y-3">
            <div className="flex items-baseline justify-between gap-2 border-b border-ink/[0.06] pb-3">
              <dt className="text-[12px] font-medium text-ink/55">Delivery queue</dt>
              <dd className="text-[13px] font-bold tabular-nums text-ink">
                {fmtNum(data.outbox_pending)} pending
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2 border-b border-ink/[0.06] pb-3">
              <dt className="text-[12px] font-medium text-ink/55">Failures</dt>
              <dd className={`text-[13px] font-bold tabular-nums ${problems > 0 ? "text-red-600" : "text-emerald-600"}`}>
                {problems > 0 ? `${fmtNum(problems)} — act now` : "none — clear"}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-[12px] font-medium text-ink/55">Listing sync</dt>
              <dd className="text-right text-[13px] font-bold text-ink" title={fmtDate(data.last_synced_at)}>
                {fmtRelative(data.last_synced_at)}
              </dd>
            </div>
          </dl>
          <p className="mt-3 rounded-xl bg-ink/[0.03] px-3 py-2.5 text-[11px] leading-relaxed text-ink/55 ring-1 ring-ink/[0.05]">
            {problems > 0 ? (
              <>Failures are losing tenant value every hour — open the logs, oldest first.</>
            ) : data.outbox_pending >= 25 ? (
              <>Queue is filling faster than it drains — check worker throughput before it becomes failures.</>
            ) : (
              <>All quiet. The next thing to watch is the 7-day sign-up line in the funnel above.</>
            )}
          </p>
          <Link
            href="/logs"
            className="mt-3 inline-flex w-full items-center justify-center rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
          >
            Open logs →
          </Link>
        </section>
      </div>

      {/* subtle footer */}
      <p className="pb-2 text-center text-[11px] text-ink/30">
        All counts live from PostgreSQL · No caching · Refresh to re-query · Read-only admin.
        {error && <span className="text-amber-600"> · Last refresh had an error: {error}</span>}
      </p>
    </div>
  );
}
