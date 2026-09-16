"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { adminFetch, type AdminOverview } from "@/lib/admin-api";

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

const STATUS_COLOR: Record<string, string> = {
  published: "bg-emerald-500",
  scheduled: "bg-sky-500",
  draft: "bg-amber-400",
  pending: "bg-violet-500",
  failed: "bg-red-500",
  archived: "bg-ink/20",
};

// ─── small atoms ─────────────────────────────────────────────────────────
function HealthDot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : warn ? "bg-amber-500" : "bg-red-500"} ${ok ? "shadow-[0_0_0_4px_rgba(16,185,129,0.15)]" : warn ? "shadow-[0_0_0_4px_rgba(245,158,11,0.15)]" : "shadow-[0_0_0_4px_rgba(239,68,68,0.15)]"}`}
    />
  );
}

function Progress({ value, max, color = "bg-deep-violet" }: { value: number; max: number; color?: string }) {
  const w = max <= 0 ? 0 : Math.min(100, Math.max(4, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink/[0.06]">
      <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${w}%` }} />
    </div>
  );
}

// ─── skeletons ───────────────────────────────────────────────────────────
function SkeletonOverview() {
  return (
    <div className="space-y-5" aria-hidden>
      <div className="h-20 animate-pulse rounded-[6px] bg-white/60" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-[6px] bg-white/60" />
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-12">
        <div className="h-56 animate-pulse rounded-[6px] bg-white/60 lg:col-span-8" />
        <div className="h-56 animate-pulse rounded-[6px] bg-white/60 lg:col-span-4" />
      </div>
      <div className="h-32 animate-pulse rounded-[6px] bg-white/60" />
    </div>
  );
}

// ─── main ────────────────────────────────────────────────────────────────
export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const o = await adminFetch<AdminOverview>("/api/v1/admin/overview");
      setData(o);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void fetchData(false);
  }, [fetchData]);

  // ── derived ───────────────────────────────────────────────────────────
  const derived = useMemo(() => {
    if (!data) return null;
    const total = data.users_total || 0;
    const verifiedRate = pct(data.users_verified, total);
    const connectionRate = pct(data.connections, total);
    const connectionRateVerified = pct(data.connections, data.users_verified || 0);
    const problems = data.outbox_failed + data.ingest_failed;
    const isHealthy = problems === 0 && data.outbox_pending < 25;
    const isDegraded = problems > 0;
    const avgReviews = total ? (data.reviews_total / total).toFixed(1) : "0";
    const avgPosts = total ? (data.posts_total / total).toFixed(1) : "0";
    const docsPerBank = data.databanks_total ? (data.documents_total / data.databanks_total).toFixed(1) : "—";
    const newShare = pct(data.signups_last_7d, total);
    const postsEntries = Object.entries(data.posts_by_status).sort((a, b) => b[1] - a[1]);
    const postsTotal = postsEntries.reduce((s, [, v]) => s + v, 0) || data.posts_total || 1;

    const tenantWithReviews = data.reviews_total > 0 ? "Yes" : "No";
    const tenantWithPosts = data.posts_total > 0 ? "Yes" : "No";

    return {
      verifiedRate,
      connectionRate,
      connectionRateVerified,
      problems,
      isHealthy,
      isDegraded,
      avgReviews,
      avgPosts,
      docsPerBank,
      newShare,
      postsEntries,
      postsTotal,
      tenantWithReviews,
      tenantWithPosts,
    };
  }, [data]);

  // ── states ────────────────────────────────────────────────────────────
  if (loading && !data) {
    return <SkeletonOverview />;
  }

  if (error && !data) {
    return (
      <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
        <p className="text-[14px] font-bold text-ink">Couldn&apos;t load overview.</p>
        <p className="mt-1 text-[12px] text-ink/50">{error}</p>
        <button onClick={() => void fetchData(false)} className="btn-primary mt-4">
          Retry
        </button>
      </div>
    );
  }

  if (!data || !derived) return null;

  const hasProblems = derived.problems > 0;

  return (
    <div className="space-y-5">
      {/* ── Header: narrative order starts with "where are we now" ───────── */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2.5 text-[20px] font-bold tracking-tight text-ink">
            Platform overview
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest ${derived.isHealthy ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : derived.isDegraded ? "bg-red-50 text-red-700 ring-1 ring-red-200" : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"}`}
            >
              <HealthDot ok={derived.isHealthy} warn={!derived.isHealthy && !derived.isDegraded} />
              {derived.isHealthy ? "healthy" : derived.isDegraded ? "needs attention" : "watch"}
            </span>
          </h1>
          <p className="mt-1 max-w-[560px] text-[12px] leading-relaxed text-ink/55">
            Live, read-only snapshot of the tenant funnel — from sign-up through verification, connection and content — plus operational health.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink/40">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 ring-1 ring-ink/[0.06]">
              <span className="h-1.5 w-1.5 rounded-full bg-deep-violet" aria-hidden />
              {data.last_synced_at ? `Last listing sync ${fmtRelative(data.last_synced_at)}` : "No listing sync yet"}
            </span>
            {updatedAt && (
              <span className="hidden sm:inline">· Updated {updatedAt.toLocaleTimeString()} · read-only</span>
            )}
            {data.last_synced_at && (
              <span className="hidden text-ink/30 sm:inline" title={fmtDate(data.last_synced_at)}>
                ({fmtDate(data.last_synced_at)})
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Link
            href="/tenants"
            className="hidden rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02] sm:inline-flex"
          >
            View tenants →
          </Link>
          <button
            onClick={() => void fetchData(true)}
            disabled={refreshing}
            aria-live="polite"
            className="inline-flex items-center gap-2 rounded-xl bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-[#4a2575] disabled:opacity-50"
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

      {/* ── 1. Urgent first: problems block ─────────────────────────────── */}
      {hasProblems && (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-[6px] border border-red-200 bg-red-50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
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
                {derived.problems} failed item{derived.problems > 1 ? "s" : ""} need attention
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-red-700/80">
                Outbox failed <b className="font-bold text-red-800">{fmtNum(data.outbox_failed)}</b> · Ingest failed{" "}
                <b className="font-bold text-red-800">{fmtNum(data.ingest_failed)}</b> · Pending{" "}
                {fmtNum(data.outbox_pending)} still in queue.
              </p>
            </div>
          </div>
          <Link
            href="/logs"
            className="shrink-0 self-start rounded-xl bg-red-600 px-3.5 py-2 text-center text-[12px] font-bold text-white transition hover:bg-red-700 sm:self-auto"
          >
            Open logs →
          </Link>
        </div>
      )}

      {/* ── 2. Primary KPIs in journey order ────────────────────────────── */}
      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading" className="sr-only">Key metrics</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {/* Tenants — acquisition */}
          <div className="group relative overflow-hidden rounded-[6px] border-2 border-white bg-white/85 p-4 shadow-sm transition hover:shadow-md">
            <div className="absolute right-0 top-0 h-20 w-20 -translate-y-6 translate-x-6 rounded-full bg-deep-violet/[0.06] blur-[1px]" aria-hidden />
            <div className="flex items-start justify-between">
              <p className="text-[11px] font-bold uppercase tracking-widest text-ink/45">Tenants</p>
              <span className="rounded-full bg-ink/[0.05] px-2 py-1 text-[10px] font-bold text-ink/50">1 · Acquisition</span>
            </div>
            <p className="mt-2 text-[26px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.users_total)}</p>
            <p className="mt-1 text-[11px] text-ink/50">
              <span className="font-semibold text-ink">{fmtNum(data.users_verified)} verified</span>{" "}
              <span className="text-ink/35">· {derived.verifiedRate}%</span>
            </p>
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between text-[10px]">
                <span className="font-semibold uppercase tracking-wide text-ink/40">Verified</span>
                <span className="tabular-nums font-bold text-ink/60">{derived.verifiedRate}%</span>
              </div>
              <Progress value={data.users_verified} max={data.users_total} />
            </div>
            <p className="mt-2.5 flex items-center gap-1.5 text-[11px]">
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${data.signups_last_7d > 0 ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-ink/[0.05] text-ink/40"}`}>
                <span aria-hidden>{data.signups_last_7d > 0 ? "↗" : "→"}</span> +{fmtNum(data.signups_last_7d)} in 7d
              </span>
              <span className="text-ink/35">{derived.newShare}% of base</span>
            </p>
          </div>

          {/* Connections — activation */}
          <div className="group relative overflow-hidden rounded-[6px] border-2 border-white bg-white/85 p-4 shadow-sm transition hover:shadow-md">
            <div className="absolute right-0 top-0 h-20 w-20 -translate-y-6 translate-x-6 rounded-full bg-sky-500/[0.07] blur-[1px]" aria-hidden />
            <div className="flex items-start justify-between">
              <p className="text-[11px] font-bold uppercase tracking-widest text-ink/45">Connected</p>
              <span className="rounded-full bg-sky-50 px-2 py-1 text-[10px] font-bold text-sky-700 ring-1 ring-sky-200">2 · Activation</span>
            </div>
            <p className="mt-2 text-[26px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.connections)}</p>
            <p className="mt-1 text-[11px] text-ink/50">
              <span className="font-semibold text-ink">{derived.connectionRate}% of tenants</span>
              <span className="text-ink/35"> · {derived.connectionRateVerified}% of verified</span>
            </p>
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between text-[10px]">
                <span className="font-semibold uppercase tracking-wide text-ink/40">Connection rate</span>
                <span className="tabular-nums font-bold text-ink/60">{derived.connectionRate}%</span>
              </div>
              <Progress value={data.connections} max={data.users_total} color="bg-sky-500" />
            </div>
            <p className="mt-2.5 truncate text-[11px] text-ink/45" title={fmtDate(data.last_synced_at)}>
              Last sync {fmtRelative(data.last_synced_at)}
            </p>
          </div>

        </div>
      </section>

      {/* ── 3. Content coverage snapshot ──────────────────────────────────── */}
      <section aria-labelledby="coverage-heading" className="rounded-[6px] border-2 border-white bg-white/85 p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[13px] font-bold uppercase tracking-widest text-ink/70">Content coverage</h3>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50">
              Tenants actively using reviews & posts — the two signals that drive AI replies & publishing.
            </p>
          </div>
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-bold text-ink/60 ring-1 ring-ink/[0.06]">
            Reviews: {derived.tenantWithReviews} · Posts: {derived.tenantWithPosts}
          </span>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex items-baseline gap-2">
            <p className="text-[28px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.reviews_total)}</p>
            <span className="text-[12px] font-medium text-ink/40">total reviews</span>
          </div>
          <div className="flex items-baseline gap-2">
            <p className="text-[28px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.posts_total)}</p>
            <span className="text-[12px] font-medium text-ink/40">total posts</span>
          </div>
          <div className="flex items-baseline gap-2">
            <p className="text-[28px] font-bold tabular-nums leading-none text-ink">{derived.avgReviews}</p>
            <span className="text-[12px] font-medium text-ink/40">avg reviews / tenant</span>
          </div>
          <div className="flex items-baseline gap-2">
            <p className="text-[28px] font-bold tabular-nums leading-none text-ink">{derived.avgPosts}</p>
            <span className="text-[12px] font-medium text-ink/40">avg posts / tenant</span>
          </div>
        </div>
        <p className="mt-3 text-[11px] leading-snug text-ink/55">
          {data.reviews_total === 0 && data.posts_total === 0
            ? "No content yet — tenants need connected listings to sync reviews and create posts."
            : data.reviews_total === 0
            ? "Posts exist but no reviews synced. Check listing connections."
            : data.posts_total === 0
            ? "Reviews syncing but no posts created. Tenants may need onboarding."
            : `Content pipeline healthy. ${fmtNum(data.reviews_total)} reviews & ${fmtNum(data.posts_total)} posts indexed.`}
        </p>
      </section>

      {/* subtle footer */}
      <p className="pb-2 text-center text-[11px] text-ink/30">
        All counts live from PostgreSQL · No caching · Refresh to re-query · Read-only admin.
        {error && <span className="text-amber-600"> · Last load had an error: {error}</span>}
      </p>
    </div>
  );
}