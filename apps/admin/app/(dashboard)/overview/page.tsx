"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  adminFetch,
  fetchAdminHealth,
  fetchLiveStats,
  fetchOverviewStats,
  type AdminHealth,
  type AdminOverview,
  type LiveStats,
  type OverviewStats,
} from "@/lib/admin-api";

// ─── helpers ───────────────────────────────────────────────────────────────
function fmtNum(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("en-US");
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

// ─── count-up (existing sections keep this) ────────────────────────────────
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
      <div className="h-10 w-64 animate-pulse rounded-[2px] bg-[var(--ui-surface)]" />
      <div className="h-24 animate-pulse rounded-[2px] bg-[var(--ui-surface)]" />
      <div className="h-52 animate-pulse rounded-[2px] bg-ink/10" />
      <div className="grid gap-3 lg:grid-cols-5">
        <div className="h-56 animate-pulse rounded-[2px] bg-[var(--ui-surface)] lg:col-span-3" />
        <div className="h-56 animate-pulse rounded-[2px] bg-[var(--ui-surface)] lg:col-span-2" />
      </div>
    </div>
  );
}

// ─── constants ─────────────────────────────────────────────────────────────
const WINDOWS: { value: string; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "90d", label: "90d" },
  { value: "1y", label: "1y" },
];

const PLATFORM_ROWS: { slug: string; label: string }[] = [
  { slug: "whatsapp", label: "WhatsApp" },
  { slug: "facebook", label: "Facebook" },
  { slug: "instagram", label: "Instagram" },
  { slug: "x", label: "X" },
  { slug: "telegram", label: "Telegram" },
  { slug: "linkedin", label: "LinkedIn" },
  { slug: "google_reviews", label: "Google Reviews" },
];

// ─── attention card ────────────────────────────────────────────────────────
function AttentionCard({
  service,
  failure,
}: {
  service: { name: string };
  failure: { message?: string | null; type?: string | null; at?: string | null } | null;
}) {
  const href = service.name.startsWith("AI:") ? "/llms" : "/logs";
  return (
    <Link
      href={href}
      className="flex items-center gap-3 rounded-[2px] border border-red-200 bg-red-50 px-4 py-3.5 transition hover:bg-red-100/50"
    >
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-red-500 text-white text-[10px]">
        !
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-bold leading-none text-red-800">{service.name}</p>
        {failure && (
          <p className="mt-0.5 text-[11px] text-red-700/80 truncate">
            {failure.message || failure.type || ""}
            {failure.at && ` · ${fmtRelative(failure.at)}`}
          </p>
        )}
      </div>
    </Link>
  );
}

// ─── main ──────────────────────────────────────────────────────────────────
export default function AdminOverviewPage() {
  const [statWindow, setStatWindow] = useState("30d");
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [liveMinutes, setLiveMinutes] = useState(30);
  const [live, setLive] = useState<LiveStats | null>(null);
  const [liveUpdatedAt, setLiveUpdatedAt] = useState<Date | null>(null);
  const [liveFails, setLiveFails] = useState(0);
  const [health, setHealth] = useState<AdminHealth | null>(null);
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [barsIn, setBarsIn] = useState(false);

  const liveInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── derived ─────────────────────────────────────────────────────────────
  const statsStale = stats !== null && stats.window !== statWindow;

  const total = data?.users_total ?? 0;
  const problems = (data?.outbox_failed ?? 0) + (data?.ingest_failed ?? 0);
  const isHealthy = problems === 0 && (data?.outbox_pending ?? 0) < 25;
  const isDegraded = problems > 0;
  const avgReviews = total ? (data?.reviews_total ?? 0) / total : 0;
  const avgPosts = total ? (data?.posts_total ?? 0) / total : 0;
  const docsPerBank = data?.databanks_total ? (data?.documents_total ?? 0) / data.databanks_total : 0;
  const postsEntries = Object.entries(data?.posts_by_status ?? {}).sort((a, b) => b[1] - a[1]);
  const postsTotal = postsEntries.reduce((s, [, v]) => s + v, 0) || (data?.posts_total ?? 0) || 1;
  const topPost: [string, number] | null = postsEntries[0] ?? null;

  const verdict = isHealthy ? "healthy" : isDegraded ? "needs attention" : "watch";

  const failingServices = health?.services.filter((s) => s.enabled && !s.ok) ?? [];
  const recentFailures = health?.recent_failures ?? [];

  // ── fetches ─────────────────────────────────────────────────────────────
  const fetchOverview = useCallback(async () => {
    try {
      const o = await adminFetch<AdminOverview>("/api/v1/admin/overview");
      setData(o);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    }
  }, []);

  const fetchStats = useCallback(async (window: string) => {
    try {
      const s = await fetchOverviewStats(window);
      setStats(s);
      setStatsError(null);
    } catch (e) {
      setStatsError(e instanceof Error ? e.message : "Stats load failed.");
    }
  }, []);

  const fetchLive = useCallback(async (minutes: number) => {
    try {
      const l = await fetchLiveStats(minutes as 30 | 60);
      setLive(l);
      setLiveUpdatedAt(new Date());
      setLiveFails(0);
    } catch {
      setLiveFails((f) => f + 1);
    }
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const h = await fetchAdminHealth();
      setHealth(h);
    } catch {
      /* health is best-effort */
    }
  }, []);

  const doRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.allSettled([
      fetchOverview(),
      fetchStats(statWindow),
      fetchLive(liveMinutes),
      fetchHealth(),
    ]);
    setRefreshing(false);
  }, [statWindow, liveMinutes, fetchOverview, fetchStats, fetchLive, fetchHealth]);

  // ── effects ─────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await fetchOverview();
      await fetchStats(statWindow);
      await fetchLive(liveMinutes);
      await fetchHealth();
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [statWindow, liveMinutes, fetchOverview, fetchStats, fetchLive, fetchHealth]);

  // Stats refires when the window pill changes.
  useEffect(() => {
    void (async () => {
      await fetchStats(statWindow);
    })();
  }, [statWindow, fetchStats]);

  // Live poll — 15s, skip when document.hidden.
  useEffect(() => {
    if (liveInterval.current) clearInterval(liveInterval.current);
    liveInterval.current = setInterval(() => {
      if (document.hidden) return;
      void fetchLive(liveMinutes);
    }, 15_000);
    return () => {
      if (liveInterval.current) clearInterval(liveInterval.current);
    };
  }, [liveMinutes, fetchLive]);

  // Health poll — 15s cycle.
  useEffect(() => {
    if (liveInterval.current) clearInterval(liveInterval.current);
    liveInterval.current = setInterval(() => {
      if (document.hidden) return;
      void fetchHealth();
    }, 15_000);
    return () => {
      if (liveInterval.current) clearInterval(liveInterval.current);
    };
  }, [fetchHealth]);

  // Funnel bars draw in after first paint.
  useEffect(() => {
    let raf = 0;
    raf = requestAnimationFrame(() => {
      raf = requestAnimationFrame(() => setBarsIn(true));
    });
    return () => cancelAnimationFrame(raf);
  }, []);

  // ── render ──────────────────────────────────────────────────────────────
  if (loading && !data && !stats) {
    return <SkeletonOverview />;
  }

  if (((error && !data) || !data) && !stats) {
    return (
      <div className="panel p-10 text-center">
        <p className="text-[14px] font-bold text-ink">Couldn&apos;t load overview.</p>
        {error && <p className="mt-1 text-[12px] text-ink/50">{error}</p>}
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            void doRefresh();
          }}
          className="btn-primary mt-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* ── masthead ─────────────────────────────────────────── */}
      <div
        className={`admin-rise flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between ${
          statsStale ? "opacity-50" : ""
        }`}
      >
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
                className={`h-1.5 w-1.5 rounded-full ${
                  isHealthy ? "bg-emerald-500" : isDegraded ? "bg-red-500" : "bg-amber-500"
                }`}
              />
              {verdict}
            </span>
          </h1>
          <p className="mt-1 text-[11px] text-ink/40">
            {data?.last_synced_at
              ? `Last listing sync ${fmtRelative(data.last_synced_at)}`
              : "No listing sync yet"}
            {updatedAt && <span> · Updated {updatedAt.toLocaleTimeString()} · read-only</span>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {/* Window segmented pill */}
          <div className="flex items-center gap-1 rounded-[2px] border border-ink/[0.12] bg-[var(--ui-surface)] px-1">
            {WINDOWS.map((w) => (
              <button
                key={w.value}
                onClick={() => setStatWindow(w.value)}
                className={`px-3 py-1.5 text-[11px] font-semibold transition ${
                  statWindow === w.value
                    ? "bg-deep-violet text-white"
                    : "text-ink/50 hover:text-ink"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
          <Link
            href="/tenants"
            className="hidden rounded-[2px] border border-ink/[0.08] bg-[var(--ui-surface)]px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet sm:inline-flex"
          >
            View tenants →
          </Link>
          <button
            onClick={() => void doRefresh()}
            disabled={refreshing}
            aria-busy={refreshing}
            className="inline-flex items-center gap-2 rounded-[2px] bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
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

      {/* ── Atttention ── */}
      {(failingServices.length > 0 || recentFailures.length > 0 || statsError) && (
        <section className="admin-rise overflow-hidden rounded-[2px] border border-red-200 bg-red-50 p-4">
          <h2 className="text-[11px] font-bold uppercase tracking-[0.16em] text-red-700 mb-3">
            Attention
          </h2>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
            <div className="flex items-center gap-1.5 text-[12px] font-bold text-red-800">
              <span className={`h-1.5 w-1.5 rounded-full bg-red-500 ${
                typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches
                  ? "animate-none"
                  : "animate-pulse"
              }`}></span>
              {failingServices.length} service{failingServices.length > 1 ? "s" : ""} degraded
            </div>
            {recentFailures.length > 0 && (
              <span className="text-[11px] text-red-600">
                {recentFailures.length} failure{recentFailures.length > 1 ? "s" : ""} in log
              </span>
            )}
          </div>
          <div className="space-y-1.5 max-h-[240px] overflow-y-auto">
            {failingServices.slice(0, 6).map((svc) => {
              const failure = recentFailures.find((f) => f.source === svc.name) || null;
              return (
                <AttentionCard key={svc.name} service={svc} failure={failure} />
              );
            })}
            {failingServices.length > 6 && (
              <p className="text-[11px] text-red-600">
                +{failingServices.length - 6} more — see all in logs
              </p>
            )}
          </div>
        </section>
      )}

      {/* ── Main facts band ── */}
      <section
        aria-labelledby="facts-heading"
        className="admin-rise overflow-hidden rounded-[2px] border border-ink/[0.08] bg-[var(--ui-surface)] p-4"
        style={{ animationDelay: "210ms" }}
      >
        <h2 id="facts-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40 mb-4">
          Platform facts
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {/* Row 1 */}
          <div className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Users</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.totals.users)}
            </p>
            {stats?.window_delta && (
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                +{fmtNum(stats.window_delta.users)} in {statWindow.toUpperCase()}
              </p>
            )}
          </div>
          <div className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Tenants</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.totals.tenants)}
            </p>
            {stats?.window_delta && (
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                +{fmtNum(stats.window_delta.tenants)} in {statWindow.toUpperCase()}
              </p>
            )}
          </div>
          <div className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Businesses</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.totals.businesses)}
            </p>
            {stats?.window_delta && (
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                +{fmtNum(stats.window_delta.businesses)} in {statWindow.toUpperCase()}
              </p>
            )}
          </div>
          <div className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Reviews</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.totals.reviews)}
            </p>
            {stats?.window_delta && (
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                +{fmtNum(stats.window_delta.reviews)} in {statWindow.toUpperCase()}
              </p>
            )}
          </div>
          {/* Row 2 */}
          <div className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Messages</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.totals.messages)}
            </p>
            {stats?.last_24h && (
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {fmtNum(stats.last_24h.messages_in)} in · {fmtNum(stats.last_24h.messages_out)} out
              </p>
            )}
            {stats?.last_24h && (
              <p className="mt-0 text-[11px] tabular-nums text-ink/40">
                {fmtNum(stats.last_24h.ai_replies)} AI
              </p>
            )}
          </div>
          <div className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Posts</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.totals.posts)}
            </p>
            {stats?.window_delta && (
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                +{fmtNum(stats.window_delta.posts)} in {statWindow.toUpperCase()}
              </p>
            )}
          </div>
          {/* Last 24h — fixed card, immune to the pill */}
          <div className="panel p-4 border-l-2 border-l-deep-violet">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Last 24h</p>
            <p className="mt-1 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(stats?.last_24h.messages)}
            </p>
            <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
              {fmtNum(stats?.last_24h.messages_in)} in · {fmtNum(stats?.last_24h.messages_out)} out ·{" "}
              {fmtNum(stats?.last_24h.ai_replies)} AI
            </p>
          </div>
          {/* Live */}
          <div className="panel p-4 border-l-2 border-l-violet-500 bg-violet/5">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
                <p className="text-[11px] font-bold uppercase tracking-widest text-violet-700">Live</p>
              </div>
              <div className="flex gap-0.5">
                <button
                  onClick={() => setLiveMinutes(30)}
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded transition ${
                    liveMinutes === 30
                      ? "bg-violet-200 text-violet-800"
                      : "text-ink/40 hover:text-ink"
                  }`}
                >
                  30m
                </button>
                <button
                  onClick={() => setLiveMinutes(60)}
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded transition ${
                    liveMinutes === 60
                      ? "bg-violet-200 text-violet-800"
                      : "text-ink/40 hover:text-ink"
                  }`}
                >
                  60m
                </button>
              </div>
            </div>
            <p className="mt-0.5 text-[30px] font-bold tabular-nums leading-none text-ink">
              {fmtNum(live?.messages_in)}
            </p>
            <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
              {fmtNum(live?.messages_in)} sent · {fmtNum(live?.ai_replies)} AI
            </p>
            <p className="mt-0 text-[11px] tabular-nums text-ink/40">
              +{fmtNum(live?.new_reviews)} reviews · +{fmtNum(live?.new_users)} users
            </p>
            <p className="mt-0.5 text-[11px]">
              <span className={`font-bold ${(live?.businesses_connected ?? 0) > 0 ? "text-emerald-300" : "text-amber-300"}`}>
                {fmtNum(live?.businesses_connected)}
              </span>{" "}
              connected /{" "}
              <span className={`font-bold ${(live?.businesses_disconnected ?? 0) > 0 ? "text-amber-300" : "text-emerald-300"}`}>
                {fmtNum(live?.businesses_disconnected)}
              </span>{" "}
              disconnected
            </p>
            <p className="mt-0.5 text-[11px] text-ink/40">
              Top: {live?.top_platform ?? "—"}
            </p>
            <p className="mt-1 text-[10px] text-ink/30">
              {liveUpdatedAt
                ? liveUpdatedAt.toLocaleTimeString()
                : liveFails >= 2
                  ? "retrying…"
                  : "—"}
            </p>
          </div>
        </div>
      </section>

      {/* ── Connected platforms panel ── */}
      {stats && (
        <section className="admin-rise overflow-hidden rounded-[2px] border border-ink/[0.08] bg-[var(--ui-surface)] p-4">
          <h2 className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40 mb-3">
            Connected platforms
          </h2>
          <div className="space-y-2">
            {PLATFORM_ROWS.map((prow) => {
              const found = stats.platforms.find((p) => p.platform === prow.slug);
              const connected = found?.connected ?? 0;
              const total = found?.connected_total ?? 0;
              const messages = found?.messages ?? 0;
              const maxMessages = Math.max(...stats.platforms.map((p) => p.messages), 1);
              const barWidth = maxMessages > 0 ? (messages / maxMessages) * 100 : 0;
              return (
                <div key={prow.slug} className="flex items-center gap-3">
                  <span className="w-24 shrink-0 text-[12px] font-medium text-ink/60">
                    {prow.label}
                  </span>
                  <span className={`w-16 shrink-0 text-[12px] font-bold tabular-nums ${connected === 0 ? "text-amber-500" : "text-ink"}`}>
                    {connected} / {total}
                  </span>
                  <span className="w-16 shrink-0 text-[12px] font-bold tabular-nums text-ink/60">
                    {fmtNum(messages)}
                  </span>
                  <div className="flex-1 h-1.5 overflow-hidden rounded-full bg-ink/[0.06]">
                    <div
                      className="h-full rounded-full bg-deep-violet transition-[width] duration-700 ease-out"
                      style={{ width: barsIn ? `${barWidth}%` : "0%" }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── the lede ── */}
      <p
        className="admin-rise max-w-[720px] text-[17px] font-medium leading-relaxed text-ink sm:text-[19px]"
        style={{ animationDelay: "70ms" }}
      >
        {total === 0 ? (
          <>No tenants yet — connect the first listing and this page starts telling the story.</>
        ) : (
          <>
            <b className="font-bold text-deep-violet">{fmtNum(total)} tenants</b>,{" "}
            <b className="font-bold text-deep-violet">{fmtNum(data?.users_verified ?? 0)} verified</b>,{" "}
            <b className="font-bold text-deep-violet">{fmtNum(data?.connections ?? 0)} connected</b>
            {" — "}
            {fmtNum(data?.reviews_total ?? 0)} reviews and {fmtNum(data?.posts_total ?? 0)} posts indexed.{" "}
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

      {/* ── urgent first: problems ── */}
      {problems > 0 && (
        <div
          role="alert"
          className="admin-rise flex flex-col gap-3 rounded-[2px] border border-red-200 bg-red-50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
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
                Outbox failed <b className="font-bold text-red-800">{fmtNum(data?.outbox_failed)}</b> · Ingest
                failed <b className="font-bold text-red-800">{fmtNum(data?.ingest_failed)}</b> · Pending{" "}
                {fmtNum(data?.outbox_pending)} still in queue.
              </p>
            </div>
          </div>
          <Link
            href="/logs"
            className="shrink-0 self-start rounded-[2px] bg-red-600 px-3.5 py-2 text-center text-[12px] font-bold text-white transition hover:bg-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 sm:self-auto"
          >
            Open logs →
          </Link>
        </div>
      )}

      {/* ── content engine + operations ── */}
      <div className="grid gap-3 lg:grid-cols-5">
        <section
          aria-labelledby="content-heading"
          className="admin-rise panel p-5 lg:col-span-3"
          style={{ animationDelay: "210ms" }}
        >
          <h2 id="content-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
            Content engine
          </h2>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data?.reviews_total ?? 0} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">reviews indexed</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {avgReviews >= 10 ? avgReviews.toFixed(0) : avgReviews.toFixed(1)} / tenant
              </p>
            </div>
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data?.posts_total ?? 0} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">posts created</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {avgPosts >= 10 ? avgPosts.toFixed(0) : avgPosts.toFixed(1)} / tenant
              </p>
            </div>
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data?.databanks_total ?? 0} />
              </p>
              <p className="mt-1 text-[11px] font-semibold text-ink/60">databanks</p>
              <p className="mt-0.5 text-[11px] tabular-nums text-ink/40">
                {fmtNum(data?.documents_total)} docs ·{" "}
                {docsPerBank >= 10 ? docsPerBank.toFixed(0) : docsPerBank.toFixed(1)}/bank
              </p>
            </div>
            <div>
              <p className="text-[30px] font-bold tabular-nums leading-none text-ink">
                <HeroNumeral value={data?.outbox_pending ?? 0} />
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
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status] ?? "bg-ink/20"}`}
                      aria-hidden
                    />
                    <span className="w-20 shrink-0 text-[11px] font-medium capitalize text-ink/60">{status}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink/[0.06]">
                      <div
                        className="h-full rounded-full bg-deep-violet transition-[width] duration-700 ease-out"
                        style={{ width: barsIn ? `${Math.max(4, (count / postsTotal) * 100)}%` : "0%" }}
                      />
                    </div>
                    <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-ink/50">
                      {fmtNum(count)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <p className="mt-4 border-t border-ink/[0.06] pt-3 text-[12px] leading-relaxed text-ink/60">
            {data?.reviews_total === 0 && data?.posts_total === 0 ? (
              <>No content yet — tenants need connected listings to sync reviews and create posts.</>
            ) : data?.reviews_total === 0 ? (
              <>Posts exist but no reviews synced. Check listing connections.</>
            ) : data?.posts_total === 0 ? (
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
          className="admin-rise panel p-5 lg:col-span-2"
          style={{ animationDelay: "280ms" }}
        >
          <h2 id="ops-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
            Operations
          </h2>
          <dl className="mt-3 space-y-3">
            <div className="flex items-baseline justify-between gap-2 border-b border-ink/[0.06] pb-3">
              <dt className="text-[12px] font-medium text-ink/55">Delivery queue</dt>
              <dd className="text-[13px] font-bold tabular-nums text-ink">
                {fmtNum(data?.outbox_pending)} pending
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
              <dd className="text-right text-[13px] font-bold text-ink" title={fmtDate(data?.last_synced_at ?? null)}>
                {fmtRelative(data?.last_synced_at ?? null)}
              </dd>
            </div>
          </dl>
          <p className="mt-3 rounded-[2px] bg-ink/[0.03] px-3 py-2.5 text-[11px] leading-relaxed text-ink/55 ring-1 ring-ink/[0.05]">
            {problems > 0 ? (
              <>Failures are losing tenant value every hour — open the logs, oldest first.</>
            ) : (data?.outbox_pending ?? 0) >= 25 ? (
              <>Queue is filling faster than it drains — check worker throughput before it becomes failures.</>
            ) : (
              <>All quiet. The next thing to watch is the 7-day sign-up line in the funnel above.</>
            )}
          </p>
          <Link
            href="/logs"
            className="mt-3 inline-flex w-full items-center justify-center rounded-[2px] border border-ink/[0.08] bg-[var(--ui-surface)]px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
          >
            Open logs →
          </Link>
        </section>
      </div>

      {/* footer */}
      <p className="pb-2 text-center text-[11px] text-ink/30">
        All counts live from PostgreSQL · No caching · Live card polls every 15s · Read-only admin.
      </p>
    </div>
  );
}