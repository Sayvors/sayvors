"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { adminFetch, type AdminTenantDetail } from "@/lib/admin-api";

type Review = AdminTenantDetail["recent_reviews"][number];

interface TenantUsage {
  days: number;
  totals: { calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number; avg_latency_ms: number };
  by_model: { model: string; api_model: string; calls: number; total_tokens: number; avg_latency_ms: number }[];
  by_purpose: { purpose: string; calls: number; total_tokens: number }[];
  daily: { day: string; total_tokens: number; calls: number }[];
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch { return iso; }
}
function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); } catch { return iso; }
}
function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return fmtDate(iso);
}
function initialsFromTenant(t: AdminTenantDetail): string {
  const a = (t.first_name?.[0] ?? t.email[0] ?? "?").toUpperCase();
  const b = (t.last_name?.[0] ?? t.email[1] ?? "").toUpperCase();
  return (a + (b && b !== a ? b : "")).slice(0, 2);
}
function sentimentStyle(s: string): string {
  const v = s.toLowerCase();
  if (v.includes("pos")) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (v.includes("neg")) return "bg-red-50 text-red-700 ring-red-200";
  if (v.includes("mix") || v.includes("neu")) return "bg-amber-50 text-amber-700 ring-amber-200";
  return "bg-ink/[0.06] text-ink/60 ring-ink/10";
}
function statusStyle(s: string): string {
  const v = s.toLowerCase();
  if (v === "published") return "bg-emerald-500 text-white";
  if (v === "scheduled") return "bg-sky-500 text-white";
  if (v === "draft") return "bg-amber-400 text-white";
  if (v === "failed") return "bg-red-500 text-white";
  if (v === "pending") return "bg-violet-500 text-white";
  return "bg-ink/10 text-ink/60";
}
function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
function fmtMs(ms: number): string { return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`; }

// Count-up numeral: animates once on first paint, final value for reduced motion.
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
  return decimals > 0 ? shown.toFixed(decimals) : Math.round(shown).toLocaleString("en-US");
}

function Stars({ rating }: { rating: number }) {
  const n = Math.max(0, Math.min(5, Math.round(rating)));
  return (
    <span role="img" aria-label={`${rating} out of 5 stars`} className="inline-flex">
      {Array.from({ length: 5 }).map((_, i) => (
        <svg key={i} width="11" height="11" viewBox="0 0 24 24" fill={i < n ? "currentColor" : "none"} className={i < n ? "text-amber-500" : "text-ink/15"} aria-hidden>
          <path d="M12 3.6l1.9 3.9 4.3.6-3.1 3 0.7 4.3L12 13.5 8.2 15.4l0.7-4.3-3.1-3 4.3-.6L12 3.6z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
      ))}
    </span>
  );
}

function MiniArea({ points }: { points: { x: string; y: number }[] }) {
  const W = 520, H = 86, PAD = 26;
  const max = Math.max(1, ...points.map((p) => p.y));
  const n = Math.max(1, points.length - 1);
  const px = (i: number) => PAD + (i / n) * (W - PAD * 2);
  const py = (v: number) => H - 14 - (v / max) * (H - 28);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
  const area = `${line} L${px(points.length - 1).toFixed(1)},${(H - 14).toFixed(1)} L${PAD},${(H - 14).toFixed(1)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full text-ink" role="img" aria-label="Daily token trend">
      <line x1={PAD} x2={W - PAD} y1={py(max)} y2={py(max)} stroke="currentColor" strokeOpacity={0.06} />
      <path d={area} fill="#5b2d8e" opacity={0.1} />
      <path d={line} fill="none" stroke="#5b2d8e" strokeWidth={1.6} strokeLinejoin="round" />
      {points.map((p, i) => <circle key={i} cx={px(i)} cy={py(p.y)} r={1.4} fill="#5b2d8e"><title>{`${p.x}: ${p.y.toLocaleString()}`}</title></circle>)}
      <text x={PAD} y={H - 3} fontSize={8.5} fill="currentColor" opacity={0.35}>{points[0]?.x ?? ""}</text>
      <text x={W - PAD} y={H - 3} textAnchor="end" fontSize={8.5} fill="currentColor" opacity={0.35}>{points[points.length - 1]?.x ?? ""}</text>
    </svg>
  );
}

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

export default function AdminTenantDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [tenant, setTenant] = useState<AdminTenantDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [selected, setSelected] = useState<Review | null>(null);
  const [usage, setUsage] = useState<TenantUsage | null>(null);
  const [usageDays, setUsageDays] = useState(30);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminFetch<AdminTenantDetail>(`/api/v1/admin/tenants/${encodeURIComponent(id)}`)
      .then((t) => { if (!cancelled) setTenant(t); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Load failed."); });
    return () => { cancelled = true; };
  }, [id]);

  // Per-tenant usage with a global-rollup fallback when the API build predates
  // the per-tenant endpoint. Promise chain only — safe inside the effect.
  useEffect(() => {
    let cancelled = false;
    setUsageLoading(true);
    setUsageError(null);
    adminFetch<TenantUsage>(`/api/v1/admin/tenants/${encodeURIComponent(id)}/usage?days=${usageDays}`)
      .then((u) => { if (!cancelled) { setUsage(u); setUsageLoading(false); } })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Usage load failed";
        const isNotFound = msg.includes("Not Found") || msg.includes("404") || msg.includes("Tenant not found");
        if (!isNotFound) {
          setUsageError(msg);
          setUsage(null);
          setUsageLoading(false);
          return;
        }
        adminFetch<{
          per_tenant: { tenant_id: string | null; email: string; calls: number; total_tokens: number; avg_latency_ms: number; last_seen: string | null }[];
        }>(`/api/v1/admin/usage/overview?days=${usageDays}`)
          .then((global) => {
            if (cancelled) return;
            const row = global.per_tenant.find((t) => t.tenant_id === id);
            setUsage({
              days: usageDays,
              totals: {
                calls: row?.calls ?? 0,
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: row?.total_tokens ?? 0,
                avg_latency_ms: row?.avg_latency_ms ?? 0,
              },
              by_model: [],
              by_purpose: [],
              daily: [],
            });
            if (row) setUsageError("Detailed per-tenant history needs an API restart — showing the global rollup. Restart the API for the full chart.");
            setUsageLoading(false);
          })
          .catch(() => {
            if (!cancelled) {
              setUsageError(msg);
              setUsage(null);
              setUsageLoading(false);
            }
          });
      });
    return () => { cancelled = true; };
  }, [id, usageDays]);

  const retryUsage = useCallback(() => {
    setUsageLoading(true);
    setUsageError(null);
    adminFetch<TenantUsage>(`/api/v1/admin/tenants/${encodeURIComponent(id)}/usage?days=${usageDays}`)
      .then((u) => { setUsage(u); })
      .catch((e: unknown) => {
        setUsageError(e instanceof Error ? e.message : "Usage load failed");
        setUsage(null);
      })
      .finally(() => setUsageLoading(false));
  }, [id, usageDays]);

  // close modal on Escape
  useEffect(() => {
    if (!selected) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [selected]);

  // usage momentum, derived outside render
  const growth = useMemo(() => {
    if (!usage || usage.daily.length < 2) return null;
    const mid = Math.floor(usage.daily.length / 2);
    const first = usage.daily.slice(0, mid).reduce((s, d) => s + d.total_tokens, 0);
    const second = usage.daily.slice(mid).reduce((s, d) => s + d.total_tokens, 0);
    return first ? Math.round(((second - first) / first) * 100) : 0;
  }, [usage]);

  if (error) {
    return (
      <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
        <p className="text-[14px] font-bold text-ink">{error}</p>
        <p className="mt-1 text-[12px] text-ink/45">Tenant ID: {id}</p>
        <Link href="/tenants" className={`mt-4 inline-flex rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white hover:bg-[#4a2575] ${FOCUS_RING}`}>← Back to tenants</Link>
      </div>
    );
  }
  if (!tenant) {
    return (
      <div className="space-y-4" aria-hidden aria-label="Loading tenant">
        <div className="h-6 w-40 animate-pulse rounded-full bg-white/60" />
        <div className="h-24 animate-pulse rounded-[6px] bg-white/60" />
        <div className="h-52 animate-pulse rounded-[6px] bg-ink/10" />
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="h-64 animate-pulse rounded-[6px] bg-white/60" />
          <div className="h-64 animate-pulse rounded-[6px] bg-white/60" />
        </div>
      </div>
    );
  }

  const name = [tenant.first_name, tenant.last_name].filter(Boolean).join(" ");
  const displayName = name || tenant.email.split("@")[0];
  const maxModelTokens = Math.max(1, ...(usage?.by_model.map((m) => m.total_tokens) ?? [1]));

  const stage: 1 | 2 | 3 = tenant.has_connection ? 3 : tenant.email_verified ? 2 : 1;
  const stageLabel = stage === 3 ? "Active" : stage === 2 ? "Verified · unconnected" : "Signed up · unverified";
  const stagePill =
    stage === 3
      ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
      : stage === 2
        ? "bg-sky-50 text-sky-700 ring-1 ring-sky-200"
        : "bg-amber-50 text-amber-700 ring-1 ring-amber-200";

  // review facts from the recent sample
  const reviewCount = tenant.recent_reviews.length;
  const avgRating = reviewCount > 0 ? tenant.recent_reviews.reduce((s, r) => s + r.rating, 0) / reviewCount : 0;
  const repliedCount = tenant.recent_reviews.filter((r) => r.replied).length;
  const replyRate = reviewCount > 0 ? Math.round((repliedCount / reviewCount) * 100) : 0;
  const publishedRecent = tenant.recent_posts.filter((p) => p.status.toLowerCase() === "published").length;

  return (
    <div className="space-y-5">
      {/* ── breadcrumb ─────────────────────────────────────── */}
      <nav aria-label="Breadcrumb" className="admin-rise flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[12px]">
          <Link
            href="/tenants"
            className={`inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 font-semibold text-ink/60 ring-1 ring-ink/[0.06] transition hover:bg-ink/[0.03] hover:text-ink ${FOCUS_RING}`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M14.5 6l-6 6 6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
            Tenants
          </Link>
          <span className="text-ink/20" aria-hidden>›</span>
          <span className="max-w-[260px] truncate font-semibold text-ink" title={tenant.email}>{tenant.email}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden truncate rounded-full bg-ink/[0.04] px-2.5 py-1 font-mono text-[11px] text-ink/50 sm:inline-flex" title={tenant.id}>
            {tenant.id.slice(0, 8)}…{tenant.id.slice(-4)}
          </span>
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(tenant.id);
                setCopied(true);
                setTimeout(() => setCopied(false), 1400);
              } catch { /* clipboard unavailable */ }
            }}
            aria-live="polite"
            className={`rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] hover:text-ink ${FOCUS_RING}`}
          >
            {copied ? "Copied!" : "Copy ID"}
          </button>
        </div>
      </nav>

      {/* ── identity + lede ────────────────────────────────── */}
      <div className="admin-rise" style={{ animationDelay: "70ms" }}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[6px] bg-deep-violet text-[15px] font-black tracking-tight text-white ring-1 ring-deep-violet/20" aria-hidden>
            {initialsFromTenant(tenant)}
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-[22px] font-bold leading-none tracking-tight text-ink" title={tenant.email}>
              {displayName}
            </h1>
            <p className="mt-1 truncate text-[12px] text-ink/50" title={tenant.email}>
              {name ? `${tenant.email} · ` : ""}
              joined {fmtDate(tenant.created_at)} · {fmtRelative(tenant.created_at)}
            </p>
          </div>
          <span className={`ml-auto inline-flex shrink-0 items-center rounded-full px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide ${stagePill}`}>
            {stageLabel}
          </span>
        </div>
        <p className="mt-3 max-w-[760px] text-[16px] font-medium leading-relaxed text-ink sm:text-[18px]">
          <b className="font-bold text-deep-violet">{displayName}</b> joined {fmtRelative(tenant.created_at)}
          {tenant.email_verified ? (
            ", verified"
          ) : (
            <>
              , <b className="font-bold text-amber-700">not verified</b>
            </>
          )}{" "}and{" "}
          {tenant.has_connection ? (
            <>connected <b className="font-bold text-deep-violet">{tenant.listing_name ?? "a listing"}</b></>
          ) : (
            "connected nothing yet"
          )}{" "}
          — {tenant.reviews.toLocaleString()} reviews, {tenant.posts.toLocaleString()} posts
          {usage && usage.totals.calls > 0 ? <>, {fmt(usage.totals.total_tokens)} AI tokens in {usage.days}d</> : null}.{" "}
          {stage < 3 ? (
            <span className="font-semibold text-amber-700">
              {stage === 1 ? "Next: verify the email — nothing can sync until then." : "Next: connect a listing — verified but idle."}
            </span>
          ) : tenant.last_synced_at ? (
            <span className="text-ink/60">Last sync {fmtRelative(tenant.last_synced_at)}.</span>
          ) : (
            <span className="text-ink/60">Connected but never synced — check the listing.</span>
          )}
        </p>
      </div>

      {/* ── dossier band ───────────────────────────────────── */}
      <section
        aria-labelledby="dossier-heading"
        className="admin-rise overflow-hidden rounded-[6px] bg-[#15102e] p-5 sm:p-6"
        style={{ animationDelay: "140ms" }}
      >
        <h2 id="dossier-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-white/40">
          Dossier · recent sample
        </h2>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4 lg:divide-x lg:divide-white/10">
          <div className="lg:pl-6 lg:first:pl-0">
            <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">Reviews indexed</dt>
            <dd className="mt-1 text-[40px] font-bold tabular-nums leading-none text-white sm:text-[46px]">
              {tenant.reviews.toLocaleString()}
            </dd>
            <dd className="mt-1.5 text-[11px] text-white/45">
              {tenant.listing_name ? <>from {tenant.listing_name}</> : "no listing connected"}
            </dd>
          </div>
          <div className="lg:pl-6">
            <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">Avg rating</dt>
            <dd className="mt-1 text-[40px] font-bold tabular-nums leading-none text-white sm:text-[46px]">
              {reviewCount > 0 ? avgRating.toFixed(1) : "—"}
              {reviewCount > 0 && <span className="text-[20px] text-white/40"> / 5</span>}
            </dd>
            <dd className="mt-1.5 text-[11px] text-white/45">
              {reviewCount > 0 ? `across ${reviewCount} recent reviews` : "no reviews to score"}
            </dd>
          </div>
          <div className="lg:pl-6">
            <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">Reply rate</dt>
            <dd className="mt-1 text-[40px] font-bold tabular-nums leading-none text-white sm:text-[46px]">
              {reviewCount > 0 ? `${replyRate}%` : "—"}
            </dd>
            <dd className="mt-1.5 text-[11px] text-white/45">
              {reviewCount > 0 ? `${repliedCount} of ${reviewCount} recent answered` : "nothing to answer yet"}
            </dd>
          </div>
          <div className="lg:pl-6">
            <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/40">Posts</dt>
            <dd className="mt-1 text-[40px] font-bold tabular-nums leading-none text-white sm:text-[46px]">
              {tenant.posts.toLocaleString()}
            </dd>
            <dd className="mt-1.5 text-[11px] text-white/45">
              {tenant.recent_posts.length > 0
                ? `${publishedRecent} of ${tenant.recent_posts.length} recent published`
                : `${tenant.databanks} knowledge banks`}
            </dd>
          </div>
        </dl>
      </section>

      {/* ── AI usage ───────────────────────────────────────── */}
      <section
        aria-labelledby="usage-heading"
        className="admin-rise rounded-[6px] border-2 border-white bg-white/85 p-4 shadow-sm sm:p-5"
        style={{ animationDelay: "210ms" }}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 id="usage-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
              AI usage · this tenant
            </h2>
            <p className="mt-1.5 text-[13px] font-medium leading-relaxed text-ink/60">
              {usage && usage.totals.calls > 0 ? (
                <>
                  <b className="font-bold text-deep-violet">{fmt(usage.totals.total_tokens)} tokens</b> across{" "}
                  <b className="font-bold text-ink">{usage.totals.calls.toLocaleString()} calls</b> in {usage.days}d
                  {growth !== null && growth !== 0 ? (
                    <> — <span className={growth > 0 ? "font-bold text-emerald-600" : "font-bold text-red-600"}>{growth > 0 ? "↗" : "↘"} {Math.abs(growth)}%</span> second half vs first</>
                  ) : null}
                  . Avg latency {fmtMs(usage.totals.avg_latency_ms)}
                  {usage.totals.avg_latency_ms > 3000 ? " — slow, check the provider." : "."}
                </>
              ) : (
                "Tokens, calls and models for this tenant only — spot power use, stalls, and cost."
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 rounded-xl bg-ink/[0.04] p-1" role="group" aria-label="Usage window">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setUsageDays(d)}
                aria-pressed={usageDays === d}
                className={`rounded-lg px-3 py-1 text-[11px] font-bold transition ${usageDays === d ? "bg-deep-violet text-white shadow-sm" : `text-ink/50 hover:bg-white hover:text-ink ${FOCUS_RING}`}`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {usageLoading ? (
          <div className="mt-4 grid gap-2.5 sm:grid-cols-4" aria-hidden aria-label="Loading usage">
            {[1, 2, 3, 4].map((i) => <div key={i} className="h-20 animate-pulse rounded-[6px] bg-ink/[0.04]" />)}
          </div>
        ) : usage ? (
          <>
            {usageError && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[11px] leading-relaxed text-amber-800">
                {usageError} <button onClick={retryUsage} className={`ml-1 font-bold underline ${FOCUS_RING}`}>Retry</button>
              </div>
            )}
            {usage.totals.calls === 0 ? (
              <div className="mt-4 rounded-[6px] border border-dashed border-ink/10 bg-ink/[0.02] p-8 text-center">
                <p className="text-[13px] font-semibold text-ink/70">No AI usage in last {usage.days}d</p>
                <p className="mx-auto mt-1 max-w-[440px] text-[12px] leading-relaxed text-ink/45">
                  This tenant hasn’t triggered a single LLM call. Nudge them to try AI features, or check provider keys in{" "}
                  <Link href="/llms" className={`font-semibold text-deep-violet hover:underline ${FOCUS_RING}`}>LLMs</Link>.
                </p>
              </div>
            ) : (
              <>
                <dl className="mt-4 grid gap-2.5 sm:grid-cols-4">
                  {[
                    { label: "Total tokens", value: fmt(usage.totals.total_tokens), note: `${usage.totals.prompt_tokens.toLocaleString()} prompt · ${usage.totals.completion_tokens.toLocaleString()} completion` },
                    { label: "Calls", value: usage.totals.calls.toLocaleString(), note: `${fmt(usage.totals.total_tokens / Math.max(1, usage.totals.calls))}/call avg` },
                    { label: "Avg latency", value: fmtMs(usage.totals.avg_latency_ms), note: usage.totals.avg_latency_ms > 3000 ? "Slow — check provider" : usage.totals.avg_latency_ms > 1500 ? "Moderate" : "Fast" },
                    { label: "Momentum", value: growth === null ? "—" : `${growth >= 0 ? "↗" : "↘"} ${Math.abs(growth)}%`, note: `${usage.daily.length} active days` },
                  ].map((c) => (
                    <div key={c.label} className="rounded-[6px] bg-ink/[0.02] px-3.5 py-3 ring-1 ring-ink/[0.04]">
                      <dt className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{c.label}</dt>
                      <dd className="mt-1 text-[18px] font-bold leading-none tabular-nums text-ink">{c.value}</dd>
                      <dd className="mt-1 text-[11px] text-ink/45">{c.note}</dd>
                    </div>
                  ))}
                </dl>

                <div className="mt-4 grid gap-4 lg:grid-cols-5">
                  <div className="rounded-[6px] bg-ink/[0.02] p-3.5 ring-1 ring-ink/[0.04] lg:col-span-3">
                    <p className="text-[11px] font-bold uppercase tracking-wide text-ink/50">Daily tokens · {usage.days}d</p>
                    {usage.daily.length === 0 ? (
                      <p className="mt-2 text-[11px] text-ink/40">No daily points.</p>
                    ) : (
                      <MiniArea points={usage.daily.map((d) => ({ x: d.day.slice(5), y: d.total_tokens }))} />
                    )}
                  </div>
                  <div className="space-y-3 lg:col-span-2">
                    <div className="rounded-[6px] bg-white p-3.5 ring-1 ring-ink/[0.06]">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-ink/50">By model</p>
                      {usage.by_model.length === 0 ? (
                        <p className="mt-2 text-[11px] text-ink/40">No model breakdown.</p>
                      ) : (
                        <div className="mt-2 space-y-2">
                          {usage.by_model.slice(0, 5).map((m) => (
                            <div key={m.model}>
                              <div className="flex items-center justify-between gap-2 text-[11px]">
                                <span className="truncate font-semibold text-ink" title={m.model}>{m.model.split(":").pop()}</span>
                                <span className="shrink-0 tabular-nums text-ink/50">{fmt(m.total_tokens)} · {m.calls}</span>
                              </div>
                              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink/[0.06]">
                                <div className="h-full rounded-full bg-deep-violet" style={{ width: `${Math.max(3, (m.total_tokens / maxModelTokens) * 100)}%` }} />
                              </div>
                            </div>
                          ))}
                          {usage.by_model.length > 5 && <p className="text-[11px] text-ink/30">+{usage.by_model.length - 5} more models</p>}
                        </div>
                      )}
                    </div>
                    <div className="rounded-[6px] bg-violet-50 p-3.5 ring-1 ring-violet-100">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-violet-700/60">By purpose</p>
                      {usage.by_purpose.length === 0 ? (
                        <p className="mt-1 text-[11px] text-ink/40">No purpose tagged.</p>
                      ) : (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {usage.by_purpose.slice(0, 6).map((p) => (
                            <span key={p.purpose} className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-ink ring-1 ring-violet-200">
                              {p.purpose} <span className="rounded-full bg-violet-500 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-white">{fmt(p.total_tokens)}</span>
                            </span>
                          ))}
                        </div>
                      )}
                      <Link href="/usage" className={`mt-3 inline-flex text-[11px] font-semibold text-deep-violet hover:underline ${FOCUS_RING}`}>Open global usage →</Link>
                    </div>
                  </div>
                </div>
              </>
            )}
          </>
        ) : usageError ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-[12px] leading-relaxed text-amber-800">
            {usageError}{" "}
            <button onClick={retryUsage} className={`font-bold underline ${FOCUS_RING}`}>Retry</button>
            <span className="ml-1 text-amber-700/70">· Restart the API to enable full per-tenant history if needed.</span>
          </div>
        ) : null}
      </section>

      {/* ── reviews + posts ──────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section
          aria-labelledby="reviews-heading"
          className="admin-rise rounded-[6px] border-2 border-white bg-white/80 p-5 shadow-sm"
          style={{ animationDelay: "280ms" }}
        >
          <div className="flex items-baseline justify-between gap-2">
            <h2 id="reviews-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
              Recent reviews
            </h2>
            <p className="text-[11px] tabular-nums text-ink/45">
              {reviewCount > 0 ? (
                <>avg <b className="font-bold text-ink">{avgRating.toFixed(1)}★</b> · {replyRate}% replied — click a card to expand</>
              ) : (
                "nothing synced yet"
              )}
            </p>
          </div>
          {reviewCount === 0 ? (
            <div className="mt-4 rounded-[6px] border border-dashed border-ink/10 bg-ink/[0.02] p-8 text-center">
              <p className="text-[13px] font-semibold text-ink/70">No reviews synced yet</p>
              <p className="mx-auto mt-1 max-w-[320px] text-[12px] leading-relaxed text-ink/45">
                Once the listing syncs, Google reviews land here with sentiment and reply status.
              </p>
            </div>
          ) : (
            <ul className="mt-4 space-y-3">
              {tenant.recent_reviews.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(r)}
                    aria-label={`Open review by ${r.reviewer ?? "Google user"}, ${r.rating} stars`}
                    className={`group w-full rounded-[6px] bg-ink/[0.02] p-3.5 text-left ring-1 ring-ink/[0.04] transition hover:bg-white hover:shadow-sm hover:ring-deep-violet/20 ${FOCUS_RING}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Stars rating={r.rating} />
                        <span className="text-[12px] font-semibold text-ink group-hover:text-deep-violet">{r.reviewer ?? "Google user"}</span>
                        <span className="text-[11px] text-ink/40">{r.created_at ? fmtRelative(r.created_at) : ""}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide ring-1 ${sentimentStyle(r.sentiment)}`}>{r.sentiment}</span>
                        {r.replied ? (
                          <span className="rounded-full bg-emerald-500 px-2 py-1 text-[10px] font-bold uppercase text-white">replied</span>
                        ) : (
                          <span className="rounded-full bg-white px-2 py-1 text-[10px] font-bold uppercase text-ink/40 ring-1 ring-ink/10">not replied</span>
                        )}
                      </div>
                    </div>
                    <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-ink/65 group-hover:text-ink/80">
                      {r.text || <span className="italic text-ink/35">(star rating only — no text)</span>}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section
          aria-labelledby="posts-heading"
          className="admin-rise rounded-[6px] border-2 border-white bg-white/80 p-5 shadow-sm"
          style={{ animationDelay: "340ms" }}
        >
          <div className="flex items-baseline justify-between gap-2">
            <h2 id="posts-heading" className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">
              Recent posts
            </h2>
            <p className="text-[11px] tabular-nums text-ink/45">
              {tenant.recent_posts.length > 0 ? `${publishedRecent} of ${tenant.recent_posts.length} published` : "nothing created yet"}
            </p>
          </div>
          {tenant.recent_posts.length === 0 ? (
            <div className="mt-4 rounded-[6px] border border-dashed border-ink/10 bg-ink/[0.02] p-8 text-center">
              <p className="text-[13px] font-semibold text-ink/70">No posts yet</p>
              <p className="mx-auto mt-1 max-w-[320px] text-[12px] leading-relaxed text-ink/45">
                The composer is idle — {tenant.has_connection ? "the listing is connected, posts should follow." : "connect a listing first."}
              </p>
            </div>
          ) : (
            <ul className="mt-4 space-y-2.5">
              {tenant.recent_posts.map((p) => (
                <li key={p.id} className="flex items-center gap-3 rounded-[6px] bg-ink/[0.02] p-3.5 ring-1 ring-ink/[0.04]">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold leading-none text-ink" title={p.title || "(untitled)"}>
                      {p.title || <span className="italic text-ink/40">(untitled)</span>}
                    </p>
                    <p className="mt-1.5 text-[11px] tabular-nums text-ink/40" title={p.created_at ? fmtDateTime(p.created_at) : ""}>
                      {p.created_at ? `${fmtDate(p.created_at)} · ${fmtRelative(p.created_at)}` : "—"}
                    </p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${statusStyle(p.status)}`}>{p.status}</span>
                </li>
              ))}
            </ul>
          )}
          <dl className="mt-4 grid grid-cols-3 gap-2 rounded-xl bg-ink/[0.02] p-2.5 text-center ring-1 ring-ink/[0.04]">
            {[
              { label: "reviews", value: tenant.reviews.toLocaleString() },
              { label: "posts", value: tenant.posts.toLocaleString() },
              { label: "banks", value: tenant.databanks.toLocaleString() },
            ].map((s) => (
              <div key={s.label}>
                <dd className="text-[15px] font-bold tabular-nums text-ink">{s.value}</dd>
                <dt className="text-[10px] font-bold uppercase tracking-widest text-ink/40">{s.label}</dt>
              </div>
            ))}
          </dl>
        </section>
      </div>

      {/* ── review modal ─────────────────────────────────── */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button type="button" aria-label="Close review" onClick={() => setSelected(null)} className={`absolute inset-0 bg-ink/40 backdrop-blur-sm ${FOCUS_RING}`} />
          <div role="dialog" aria-modal="true" aria-labelledby="review-title" className="relative max-h-[85vh] w-full max-w-[560px] overflow-auto rounded-[6px] border-2 border-white bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p id="review-title" className="flex items-center gap-2 text-[13px] font-bold text-ink">
                  <Stars rating={selected.rating} />
                  <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[11px] font-bold tabular-nums">{selected.rating}★</span>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ring-1 ${sentimentStyle(selected.sentiment)}`}>{selected.sentiment}</span>
                </p>
                <p className="mt-1 text-[12px] font-semibold text-ink">{selected.reviewer ?? "Google user"}</p>
                <p className="text-[11px] tabular-nums text-ink/45">
                  {selected.created_at ? fmtDateTime(selected.created_at) : ""} · {selected.created_at ? fmtRelative(selected.created_at) : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {selected.replied ? (
                  <span className="rounded-full bg-emerald-500 px-2.5 py-1 text-[11px] font-bold uppercase text-white">Replied</span>
                ) : (
                  <span className="rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-bold uppercase text-ink/50">Not replied</span>
                )}
                <button onClick={() => setSelected(null)} autoFocus className={`rounded-xl bg-ink px-3 py-1.5 text-[12px] font-bold text-white hover:bg-ink/90 ${FOCUS_RING}`}>
                  Close
                </button>
              </div>
            </div>
            <div className="mt-4 rounded-[6px] bg-ink/[0.03] p-4 ring-1 ring-ink/[0.06]">
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink/80">{selected.text || "(No text — star rating only)"}</p>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button
                onClick={async () => { try { await navigator.clipboard.writeText(selected.text || ""); } catch { /* clipboard unavailable */ } }}
                className={`rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.03] ${FOCUS_RING}`}
              >
                Copy text
              </button>
              <span className="rounded-full bg-white px-3 py-2 text-[11px] tabular-nums text-ink/40 ring-1 ring-ink/[0.06]">ID {selected.id.slice(0, 8)}…</span>
            </div>
            <p className="mt-3 text-center text-[11px] text-ink/30">Click outside to close · Esc</p>
          </div>
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-ink/25">Tenant ID {tenant.id} · Read-only view · Data live from PostgreSQL</p>
    </div>
  );
}
