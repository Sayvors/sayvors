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
      <div className="h-20 animate-pulse rounded-2xl bg-white/60" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-2xl bg-white/60" />
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-12">
        <div className="h-56 animate-pulse rounded-2xl bg-white/60 lg:col-span-8" />
        <div className="h-56 animate-pulse rounded-2xl bg-white/60 lg:col-span-4" />
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-40 animate-pulse rounded-2xl bg-white/60" />
        ))}
      </div>
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
    };
  }, [data]);

  // ── states ────────────────────────────────────────────────────────────
  if (loading && !data) {
    return <SkeletonOverview />;
  }

  if (error && !data) {
    return (
      <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
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
          className="flex flex-col gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
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
          <div className="group relative overflow-hidden rounded-2xl border-2 border-white bg-white/85 p-4 shadow-sm transition hover:shadow-md">
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
          <div className="group relative overflow-hidden rounded-2xl border-2 border-white bg-white/85 p-4 shadow-sm transition hover:shadow-md">
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

          {/* Reviews — value */}
          <div className="group relative overflow-hidden rounded-2xl border-2 border-white bg-white/85 p-4 shadow-sm transition hover:shadow-md">
            <div className="absolute right-0 top-0 h-20 w-20 -translate-y-6 translate-x-6 rounded-full bg-amber-400/[0.10] blur-[1px]" aria-hidden />
            <div className="flex items-start justify-between">
              <p className="text-[11px] font-bold uppercase tracking-widest text-ink/45">Reviews synced</p>
              <span className="rounded-full bg-amber-50 px-2 py-1 text-[10px] font-bold text-amber-700 ring-1 ring-amber-200">3 · Value</span>
            </div>
            <p className="mt-2 text-[26px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.reviews_total)}</p>
            <p className="mt-1 text-[11px] text-ink/50">
              <span className="font-semibold text-ink">{derived.avgReviews} avg</span> per tenant
            </p>
            <div className="mt-3 rounded-xl bg-amber-50/70 px-2.5 py-2 ring-1 ring-amber-100">
              <p className="text-[10px] font-bold uppercase tracking-wide text-amber-700/70">Coverage</p>
              <p className="mt-0.5 text-[11px] leading-snug text-ink/60">
                {data.reviews_total === 0
                  ? "No reviews yet — tenants need a connected listing to sync."
                  : `${fmtNum(data.reviews_total)} review insights indexed for AI replies.`}
              </p>
            </div>
          </div>

          {/* Posts — creation */}
          <div className="group relative overflow-hidden rounded-2xl border-2 border-white bg-white/85 p-4 shadow-sm transition hover:shadow-md">
            <div className="absolute right-0 top-0 h-20 w-20 -translate-y-6 translate-x-6 rounded-full bg-emerald-500/[0.08] blur-[1px]" aria-hidden />
            <div className="flex items-start justify-between">
              <p className="text-[11px] font-bold uppercase tracking-widest text-ink/45">Posts</p>
              <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200">4 · Creation</span>
            </div>
            <p className="mt-2 text-[26px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.posts_total)}</p>
            <p className="mt-1 text-[11px] text-ink/50">
              <span className="font-semibold text-ink">{derived.avgPosts} avg</span> per tenant · {derived.postsEntries.length} status{derived.postsEntries.length !== 1 ? "es" : ""}
            </p>
            {derived.postsEntries.length > 0 ? (
              <div className="mt-3">
                <div className="flex h-2 overflow-hidden rounded-full bg-ink/[0.06]">
                  {derived.postsEntries.map(([k, v]) => (
                    <div
                      key={k}
                      className={`${STATUS_COLOR[k] ?? "bg-ink/30"} h-full`}
                      style={{ width: `${(v / derived.postsTotal) * 100}%` }}
                      title={`${k}: ${v}`}
                    />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {derived.postsEntries.slice(0, 4).map(([k, v]) => (
                    <span
                      key={k}
                      className="inline-flex items-center gap-1.5 rounded-full bg-ink/[0.04] px-2 py-1 text-[10px] font-semibold text-ink/60"
                    >
                      <span className={`h-2 w-2 rounded-full ${STATUS_COLOR[k] ?? "bg-ink/30"}`} aria-hidden />
                      {k} <b className="font-bold text-ink/80">{fmtNum(v)}</b>
                    </span>
                  ))}
                  {derived.postsEntries.length > 4 && (
                    <span className="text-[10px] font-medium text-ink/35">+{derived.postsEntries.length - 4} more</span>
                  )}
                </div>
              </div>
            ) : (
              <p className="mt-3 rounded-xl bg-ink/[0.03] px-2.5 py-2 text-[11px] text-ink/40">No posts yet.</p>
            )}
          </div>
        </div>
      </section>

      {/* ── 3. Funnel + Operations: the two halves of "how we run" ─────── */}
      <div className="grid gap-3 lg:grid-cols-12">
        {/* Tenant funnel — left 8 */}
        <section className="rounded-2xl border-2 border-white bg-white/85 p-5 shadow-sm lg:col-span-8">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[13px] font-bold uppercase tracking-widest text-ink/70">Tenant funnel</h2>
              <p className="mt-1 text-[12px] leading-relaxed text-ink/50">
                Every tenant moves left → right. Drop-off between steps tells you where to act.
              </p>
            </div>
            <Link
              href="/tenants"
              className="rounded-xl bg-ink/[0.04] px-3 py-1.5 text-[11px] font-bold text-ink/60 transition hover:bg-ink/[0.06] hover:text-ink"
            >
              Browse tenants →
            </Link>
          </div>

          {/* funnel bars */}
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              {
                step: "01",
                label: "Signed up",
                value: data.users_total,
                note: `${fmtNum(data.signups_last_7d)} new in 7d`,
                pct: 100,
                color: "bg-deep-violet",
              },
              {
                step: "02",
                label: "Verified email",
                value: data.users_verified,
                note: `${derived.verifiedRate}% of signups`,
                pct: derived.verifiedRate,
                color: "bg-violet-500",
              },
              {
                step: "03",
                label: "Connected listing",
                value: data.connections,
                note: `${derived.connectionRate}% of signups · ${derived.connectionRateVerified}% of verified`,
                pct: derived.connectionRate,
                color: "bg-sky-500",
              },
            ].map((s) => (
              <div key={s.label} className="rounded-2xl bg-ink/[0.02] p-3 ring-1 ring-ink/[0.04]">
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-bold text-ink/40 ring-1 ring-ink/[0.06]">{s.step}</span>
                  <span className="text-[11px] font-bold uppercase tracking-wide text-ink/60">{s.label}</span>
                </div>
                <p className="mt-2 text-[22px] font-bold tabular-nums leading-none text-ink">{fmtNum(s.value)}</p>
                <p className="mt-1 text-[11px] leading-snug text-ink/45">{s.note}</p>
                <div className="mt-3">
                  <Progress value={s.pct} max={100} color={s.color} />
                </div>
              </div>
            ))}
          </div>

          {/* funnel summary + verification gap */}
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl bg-deep-violet/[0.04] px-3.5 py-3 ring-1 ring-deep-violet/10">
              <p className="text-[11px] font-bold uppercase tracking-wide text-deep-violet/70">Conversion insight</p>
              <p className="mt-1 text-[12px] leading-relaxed text-ink/70">
                <b className="font-bold text-ink">{data.users_total - data.users_verified} tenants</b> haven&apos;t verified email yet.
                {derived.verifiedRate < 60 && " Focus onboarding nudges here."}
                {derived.connectionRate < 40 && (
                  <>
                    {" "}
                    <b className="font-bold text-ink">{data.users_verified - data.connections} verified</b> haven&apos;t connected a
                    listing — the biggest activation gap.
                  </>
                )}
              </p>
            </div>
            <div className="rounded-xl bg-white px-3.5 py-3 ring-1 ring-ink/[0.06]">
              <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40">Next step for ops</p>
              <p className="mt-1 text-[12px] leading-relaxed text-ink/60">
                Check <Link href="/tenants" className="font-semibold text-deep-violet hover:underline">Tenants</Link> sorted by &quot;unverified&quot; or
                missing listing, then trigger a re-sync from{" "}
                <Link href="/logs" className="font-semibold text-deep-violet hover:underline">Logs</Link>.
              </p>
            </div>
          </div>
        </section>

        {/* Operations — right 4 */}
        <section
          className={`rounded-2xl border-2 bg-white/85 p-5 shadow-sm lg:col-span-4 ${hasProblems ? "border-red-200 bg-red-50/40" : "border-white"}`}
        >
          <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-widest text-ink/70">
            Pipeline health
            <HealthDot ok={!hasProblems && data.outbox_pending < 25} warn={!hasProblems && data.outbox_pending >= 25} />
          </h2>
          <p className="mt-1 text-[12px] text-ink/50">Async jobs — what&apos;s queued, what failed, what to fix first.</p>

          <div className="mt-4 space-y-3">
            {[
              {
                label: "Outbox pending",
                value: data.outbox_pending,
                hint: "Queued events waiting to send. Normal if &lt; 50.",
                ok: data.outbox_pending < 50,
                warn: data.outbox_pending >= 50 && data.outbox_pending < 200,
                to: "/logs",
              },
              {
                label: "Outbox failed",
                value: data.outbox_failed,
                hint: "Needs retry or manual fix.",
                ok: data.outbox_failed === 0,
                warn: false,
                to: "/logs",
              },
              {
                label: "Ingest failed",
                value: data.ingest_failed,
                hint: "Document ingest jobs that errored.",
                ok: data.ingest_failed === 0,
                warn: false,
                to: "/logs",
              },
            ].map((row) => (
              <Link
                key={row.label}
                href={row.to}
                className={`flex items-center justify-between gap-3 rounded-xl px-3 py-3 ring-1 transition ${row.ok ? "bg-white ring-ink/[0.06] hover:ring-ink/10" : row.warn ? "bg-amber-50 ring-amber-200 hover:ring-amber-300" : "bg-red-50 ring-red-200 hover:ring-red-300"}`}
              >
                <div>
                  <p className="flex items-center gap-2 text-[12px] font-bold text-ink">
                    <HealthDot ok={row.ok} warn={row.warn} />
                    {row.label}
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink/45">{row.hint}</p>
                </div>
                <span className={`shrink-0 rounded-xl px-3 py-1.5 text-[15px] font-bold tabular-nums ${row.ok ? "bg-ink/[0.04] text-ink" : row.warn ? "bg-amber-500 text-white" : "bg-red-600 text-white"}`}>
                  {fmtNum(row.value)}
                </span>
              </Link>
            ))}
          </div>

          <Link href="/logs" className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-xl bg-ink px-3 py-2.5 text-[12px] font-bold text-white transition hover:bg-ink/90">
            View service logs & failures →
          </Link>
          {!hasProblems && data.outbox_pending === 0 && (
            <p className="mt-2 text-center text-[11px] font-medium text-emerald-700">All queues clear. No action needed.</p>
          )}
        </section>
      </div>

      {/* ── 4. Content & knowledge — Databanks ─────────────────────────── */}
      <div className="grid gap-3 lg:grid-cols-3">
        <section className="rounded-2xl border-2 border-white bg-white/85 p-5 shadow-sm">
          <h3 className="text-[12px] font-bold uppercase tracking-widest text-ink/60">Knowledge base</h3>
          <div className="mt-3 flex items-baseline gap-2">
            <p className="text-[28px] font-bold tabular-nums leading-none text-ink">{fmtNum(data.databanks_total)}</p>
            <span className="text-[12px] font-medium text-ink/40">databanks</span>
          </div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <p className="text-[15px] font-bold tabular-nums text-ink/80">{fmtNum(data.documents_total)}</p>
            <span className="text-[11px] text-ink/40">documents indexed</span>
          </div>
          <div className="mt-4 rounded-xl bg-violet-50 px-3 py-2.5 ring-1 ring-violet-100">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-semibold uppercase tracking-wide text-violet-700/70">Avg docs / bank</span>
              <span className="font-bold tabular-nums text-violet-700">{derived.docsPerBank}</span>
            </div>
            <div className="mt-2">
              <Progress value={data.documents_total} max={Math.max(data.documents_total, data.databanks_total * 10) || 1} color="bg-violet-500" />
            </div>
            <p className="mt-2 text-[11px] leading-snug text-ink/55">
              {data.databanks_total === 0
                ? "No databanks yet — tenants create them to power chat & search."
                : data.documents_total === 0
                  ? "Banks exist but no documents ingested. Check ingest failures →"
                  : `Healthy knowledge density. Coverage grows with every synced document.`}
            </p>
          </div>
        </section>

        <section className="rounded-2xl border-2 border-white bg-white/85 p-5 shadow-sm lg:col-span-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-[12px] font-bold uppercase tracking-widest text-ink/60">Posts by status — accurate counts</h3>
              <p className="mt-1 text-[12px] text-ink/50">Live breakdown from PostgreSQL. Bars are proportional — hover for exact numbers.</p>
            </div>
            <span className="shrink-0 rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-bold tabular-nums text-ink/60">
              {fmtNum(data.posts_total)} total
            </span>
          </div>

          {derived.postsEntries.length === 0 ? (
            <p className="mt-6 rounded-xl bg-ink/[0.03] px-4 py-8 text-center text-[12px] text-ink/40">No posts yet — tenants will see an empty library.</p>
          ) : (
            <>
              <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-ink/[0.06] ring-1 ring-ink/[0.04]">
                {derived.postsEntries.map(([k, v]) => (
                  <div
                    key={k}
                    className={`${STATUS_COLOR[k] ?? "bg-ink/30"} h-full transition-all`}
                    style={{ width: `${(v / derived.postsTotal) * 100}%` }}
                    title={`${k}: ${v} (${pct(v, derived.postsTotal)}%)`}
                  />
                ))}
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {derived.postsEntries.map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between rounded-xl bg-ink/[0.02] px-3 py-2.5 ring-1 ring-ink/[0.04]">
                    <span className="flex items-center gap-2 text-[12px] font-semibold capitalize text-ink/70">
                      <span className={`h-2.5 w-2.5 rounded-full ${STATUS_COLOR[k] ?? "bg-ink/30"}`} aria-hidden />
                      {k}
                    </span>
                    <span className="flex items-baseline gap-2">
                      <b className="text-[13px] font-bold tabular-nums text-ink">{fmtNum(v)}</b>
                      <span className="text-[11px] tabular-nums text-ink/40">{pct(v, derived.postsTotal)}%</span>
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-ink/35">Statuses are exact — no sampling, no cache. Source: LocationPost.status.</p>
            </>
          )}
        </section>
      </div>

      {/* ── 5. Go deeper — ordered by operator workflow ────────────────── */}
      <section aria-labelledby="deeper-heading" className="rounded-2xl border-2 border-white bg-white/60 p-4">
        <h2 id="deeper-heading" className="text-[11px] font-bold uppercase tracking-widest text-ink/40">
          Go deeper — operator workflow
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              href: "/tenants",
              step: "01",
              title: "Tenants",
              desc: "Search by email or name, inspect a tenant's listing, reviews & posts.",
              meta: `${fmtNum(data.users_total)} users · ${fmtNum(data.users_verified)} verified`,
              accent: "bg-deep-violet",
            },
            {
              href: "/usage",
              step: "02",
              title: "Token usage",
              desc: "Global metering — calls, tokens and latency per tenant & per model.",
              meta: "Daily trend & per-tenant rails",
              accent: "bg-sky-500",
            },
            {
              href: "/logs",
              step: "03",
              title: "Logs & health",
              desc: "Service liveness + the last 20 outbox / ingest failures with live probes.",
              meta: hasProblems ? `${derived.problems} failures need triage` : "All clear",
              accent: hasProblems ? "bg-red-500" : "bg-emerald-500",
            },
            {
              href: "/llms",
              step: "04",
              title: "LLM providers",
              desc: "Keys, model toggles & live tests — the single source of truth for tenants.",
              meta: "Encrypted keys · per-model control",
              accent: "bg-amber-500",
            },
          ].map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="group relative flex flex-col overflow-hidden rounded-2xl bg-white p-4 shadow-sm ring-1 ring-ink/[0.06] transition hover:shadow-md hover:ring-ink/10"
            >
              <div className={`absolute left-0 top-0 h-1 w-full ${card.accent}`} aria-hidden />
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold text-ink/40">{card.step}</span>
                <span className="text-[13px] font-bold text-ink group-hover:text-deep-violet">{card.title} →</span>
              </div>
              <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-ink/55">{card.desc}</p>
              <p className="mt-auto pt-3 text-[11px] font-medium tabular-nums text-ink/35">{card.meta}</p>
            </Link>
          ))}
        </div>
      </section>

      {/* subtle footer */}
      <p className="pb-2 text-center text-[11px] text-ink/30">
        All counts live from PostgreSQL · No caching · Refresh to re-query · Read-only admin.
        {error && <span className="text-amber-600"> · Last load had an error: {error}</span>}
      </p>
    </div>
  );
}
