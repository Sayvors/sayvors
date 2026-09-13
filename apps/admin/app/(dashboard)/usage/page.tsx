"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface TenantRow {
  tenant_id: string | null;
  email: string;
  calls: number;
  total_tokens: number;
  avg_latency_ms: number;
  last_seen: string | null;
}
interface ModelRow {
  model: string;
  api_model: string;
  calls: number;
  total_tokens: number;
}
interface UsageOverview {
  days: number;
  totals: { calls: number; total_tokens: number; active_tenants: number };
  per_tenant: TenantRow[];
  per_model: ModelRow[];
  daily: { day: string; total_tokens: number; calls: number }[];
}

function CompactArea({ points }: { points: { x: string; y: number }[] }) {
  const W = 520;
  const H = 96;
  const PAD = 28;
  const max = Math.max(1, ...points.map((p) => p.y));
  const n = Math.max(1, points.length - 1);
  const px = (i: number) => PAD + (i / n) * (W - PAD * 2);
  const py = (v: number) => H - 16 - (v / max) * (H - 32);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
  const area = `${line} L${px(points.length - 1).toFixed(1)},${(H - 16).toFixed(1)} L${PAD},${(H - 16).toFixed(1)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full text-ink">
      {[0, 1].map((f) => {
        const t = Math.round(max * f);
        return (
          <g key={f}>
            <line x1={PAD} x2={W - PAD} y1={py(t)} y2={py(t)} stroke="currentColor" strokeOpacity={0.06} />
            <text x={PAD - 4} y={py(t) + 3} textAnchor="end" fontSize={8.5} fill="currentColor" opacity={0.4}>
              {t >= 1000 ? `${(t / 1000).toFixed(1)}K` : t}
            </text>
          </g>
        );
      })}
      <path d={area} fill="#5b2d8e" opacity={0.1} />
      <path d={line} fill="none" stroke="#5b2d8e" strokeWidth={1.7} strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={px(i)} cy={py(p.y)} r={1.4} fill="#5b2d8e">
          <title>{`${p.x}: ${p.y.toLocaleString()} tokens · ${points[i] ? "" : ""}`}</title>
        </circle>
      ))}
      <text x={PAD} y={H - 4} fontSize={8.5} fill="currentColor" opacity={0.35}>{points[0]?.x ?? ""}</text>
      <text x={W - PAD} y={H - 4} textAnchor="end" fontSize={8.5} fill="currentColor" opacity={0.35}>{points[points.length - 1]?.x ?? ""}</text>
    </svg>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}
function pct(part: number, whole: number): number {
  if (!whole) return 0;
  return Math.round((part / whole) * 100);
}

export default function UsagePage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminFetch<UsageOverview>(`/api/v1/admin/usage/overview?days=${d}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load usage");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const tenants = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return data.per_tenant;
    return data.per_tenant.filter((t) => t.email.toLowerCase().includes(q) || (t.tenant_id ?? "").toLowerCase().includes(q));
  }, [data, search]);

  const insights = useMemo(() => {
    if (!data || data.per_tenant.length === 0) return null;
    const total = data.totals.total_tokens || 1;
    const sorted = [...data.per_tenant].sort((a, b) => b.total_tokens - a.total_tokens);
    const top1 = sorted[0];
    const top1Share = pct(top1.total_tokens, total);
    const top3Share = pct(sorted.slice(0, 3).reduce((s, t) => s + t.total_tokens, 0), total);
    const avgPerTenant = Math.round(total / Math.max(1, data.totals.active_tenants));
    const avgPerCall = data.totals.calls ? Math.round(total / data.totals.calls) : 0;

    // dormant: last_seen > 7d ago
    const now = Date.now();
    const dormant = data.per_tenant.filter((t) => {
      if (!t.last_seen) return true;
      return now - new Date(t.last_seen).getTime() > 7 * 86400 * 1000;
    }).length;
    const active48h = data.per_tenant.filter((t) => t.last_seen && now - new Date(t.last_seen).getTime() < 48 * 3600 * 1000).length;

    // buckets
    const buckets = { power: 0, active: 0, light: 0 };
    for (const t of data.per_tenant) {
      if (t.total_tokens >= 10000) buckets.power++;
      else if (t.total_tokens >= 1000) buckets.active++;
      else buckets.light++;
    }

    // daily momentum
    const daily = data.daily;
    const mid = Math.floor(daily.length / 2);
    const firstHalf = daily.slice(0, mid).reduce((s, d) => s + d.total_tokens, 0);
    const secondHalf = daily.slice(mid).reduce((s, d) => s + d.total_tokens, 0);
    const growth = firstHalf ? Math.round(((secondHalf - firstHalf) / firstHalf) * 100) : 0;
    const peak = daily.reduce((m, d) => (d.total_tokens > m.total_tokens ? d : m), daily[0] ?? { day: "—", total_tokens: 0 });

    // latency
    const avgLat = Math.round(data.per_tenant.reduce((s, t) => s + t.avg_latency_ms, 0) / Math.max(1, data.per_tenant.length));
    const slow = data.per_tenant.filter((t) => t.avg_latency_ms > 3000).length;

    // model dominance
    const modelTotal = data.per_model.reduce((s, m) => s + m.total_tokens, 0) || 1;
    const leader = data.per_model[0];
    const leaderShare = leader ? pct(leader.total_tokens, modelTotal) : 0;

    return { top1, top1Share, top3Share, avgPerTenant, avgPerCall, dormant, active48h, buckets, growth, peak, avgLat, slow, leader, leaderShare };
  }, [data]);

  const maxTenant = Math.max(1, ...tenants.map((t) => t.total_tokens));
  const maxModel = Math.max(1, ...(data?.per_model.map((m) => m.total_tokens) ?? [1]));

  return (
    <div className="space-y-4">
      {/* compact header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-[18px] font-bold tracking-tight text-ink">Usage · people progress</h1>
          <p className="mt-1 max-w-[560px] text-[11px] leading-relaxed text-ink/50">
            Who is actually advancing — heavy users, rising adopters, and quiet tenants to nudge. Compact, actionable.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 rounded-xl bg-white p-1 ring-1 ring-ink/[0.06]">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1 text-[11px] font-bold transition ${days === d ? "bg-deep-violet text-white shadow-sm" : "text-ink/55 hover:bg-ink/[0.04] hover:text-ink"}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="grid gap-2.5 sm:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-[76px] animate-pulse rounded-2xl border-2 border-white bg-white/60" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-2xl border-2 border-white bg-white/80 p-8 text-center">
          <p className="text-[13px] text-ink/60">{error}</p>
          <button onClick={() => void load(days)} className="btn-primary mt-3 !py-1.5 text-[12px]">Retry</button>
        </div>
      ) : data ? (
        <>
          {/* compact KPI strip */}
          <div className="grid gap-2.5 sm:grid-cols-4">
            {[
              { label: "Total tokens", value: fmt(data.totals.total_tokens), sub: `${data.totals.calls.toLocaleString()} calls` },
              { label: "Avg / tenant", value: fmt(Math.round(data.totals.total_tokens / Math.max(1, data.totals.active_tenants))), sub: `${data.totals.active_tenants} active` },
              { label: "Avg / call", value: data.totals.calls ? fmt(Math.round(data.totals.total_tokens / data.totals.calls)) : "—", sub: `${fmt(data.totals.total_tokens)} in ${days}d` },
              { label: "Peak day", value: fmt(Math.max(0, ...data.daily.map((d) => d.total_tokens))), sub: data.daily.reduce((m, d) => (d.total_tokens > m.total_tokens ? d : m), data.daily[0] ?? { day: "—", total_tokens: 0 })?.day?.slice(5) ?? "—" },
            ].map((c) => (
              <div key={c.label} className="rounded-2xl border-2 border-white bg-white/80 px-3.5 py-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{c.label}</p>
                <p className="mt-1 text-[18px] font-bold leading-none tabular-nums text-ink">{c.value}</p>
                <p className="mt-1 text-[11px] leading-none text-ink/45">{c.sub}</p>
              </div>
            ))}
          </div>

          {/* beneficial facts — compact insight row */}
          {insights && (
            <div className="grid gap-2.5 lg:grid-cols-4">
              {/* Concentration */}
              <div className="rounded-2xl border-2 border-white bg-white/85 px-3.5 py-3">
                <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">
                  <span className="h-1.5 w-1.5 rounded-full bg-violet-500" aria-hidden /> Concentration
                </p>
                <p className="mt-1.5 text-[12px] font-semibold leading-snug text-ink">
                  Top tenant <span className="font-bold text-deep-violet">{insights.top1Share}%</span> · Top 3 <span className="font-bold text-deep-violet">{insights.top3Share}%</span>
                </p>
                <p className="mt-1 truncate text-[11px] text-ink/50" title={insights.top1.email}>{insights.top1.email} leads with {fmt(insights.top1.total_tokens)}</p>
                <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-ink/[0.06]">
                  <div className="bg-deep-violet" style={{ width: `${Math.min(100, insights.top1Share)}%` }} />
                  <div className="bg-violet-300" style={{ width: `${Math.max(0, insights.top3Share - insights.top1Share)}%` }} />
                </div>
                <p className="mt-1.5 text-[11px] leading-snug text-ink/45">
                  {insights.top3Share > 70 ? "Heavy reliance — grow mid-tier." : insights.top3Share < 40 ? "Healthy distribution — many progressing." : "Balanced — activate more power users."}
                </p>
              </div>

              {/* Engagement / dormancy */}
              <div className="rounded-2xl border-2 border-white bg-white/85 px-3.5 py-3">
                <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">
                  <span className={`h-1.5 w-1.5 rounded-full ${insights.dormant > 0 ? "bg-amber-500" : "bg-emerald-500"}`} aria-hidden /> Engagement
                </p>
                <p className="mt-1.5 text-[12px] font-semibold text-ink">
                  {insights.active48h} active 48h · <span className={insights.dormant ? "text-amber-600" : "text-emerald-600"}>{insights.dormant} dormant &gt;7d</span>
                </p>
                <div className="mt-2 flex gap-1">
                  <span className="rounded-full bg-violet-500 px-2 py-1 text-[10px] font-bold text-white">{insights.buckets.power} power</span>
                  <span className="rounded-full bg-sky-500 px-2 py-1 text-[10px] font-bold text-white">{insights.buckets.active} active</span>
                  <span className="rounded-full bg-ink/10 px-2 py-1 text-[10px] font-bold text-ink/60">{insights.buckets.light} light</span>
                </div>
                <p className="mt-1.5 text-[11px] leading-snug text-ink/45">
                  {insights.dormant > 3 ? "Nudge dormant: re-engage email + demo." : insights.buckets.power === 0 ? "No power users yet — champion 2–3 tenants." : "Retention strong — keep momentum."}
                </p>
              </div>

              {/* Momentum */}
              <div className="rounded-2xl border-2 border-white bg-white/85 px-3.5 py-3">
                <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">
                  <span className={`h-1.5 w-1.5 rounded-full ${insights.growth >= 0 ? "bg-emerald-500" : "bg-red-500"}`} aria-hidden /> Momentum
                </p>
                <p className="mt-1.5 flex items-baseline gap-1.5 text-[12px] font-semibold text-ink">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${insights.growth >= 0 ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-red-50 text-red-700 ring-1 ring-red-200"}`}>
                    {insights.growth >= 0 ? "↗" : "↘"} {Math.abs(insights.growth)}%
                  </span>
                  <span>2nd half vs 1st</span>
                </p>
                <p className="mt-1 text-[11px] text-ink/50">Peak {insights.peak.day.slice(5)} · {fmt(insights.peak.total_tokens)} tokens</p>
                <p className="mt-1.5 text-[11px] leading-snug text-ink/45">
                  {insights.growth >= 10 ? "Progress accelerating — double down on top use cases." : insights.growth <= -10 ? "Usage cooling — check model outages or tenant churn." : "Steady progress — stable adoption."}
                </p>
              </div>

              {/* Efficiency */}
              <div className="rounded-2xl border-2 border-white bg-white/85 px-3.5 py-3">
                <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">
                  <span className={`h-1.5 w-1.5 rounded-full ${insights.slow ? "bg-amber-500" : "bg-sky-500"}`} aria-hidden /> Efficiency
                </p>
                <p className="mt-1.5 text-[12px] font-semibold text-ink">{fmt(insights.avgPerCall)} / call · {insights.leaderShare}% via {insights.leader?.model.split(":").pop() ?? "—"}</p>
                <p className="mt-1 text-[11px] text-ink/50">
                  Avg latency {fmtMs(insights.avgLat)} · {insights.slow ? `${insights.slow} slow tenants >3s` : "no slow outliers"}
                </p>
                <p className="mt-1.5 text-[11px] leading-snug text-ink/45">
                  {insights.avgPerCall > 2000 ? "Heavy prompts — explore summarization." : insights.slow ? "Latency risk — inspect provider." : "Lean usage — cost efficient."}
                </p>
              </div>
            </div>
          )}

          {/* compact two-col: daily + models */}
          <div className="grid gap-3 lg:grid-cols-5">
            <div className="rounded-2xl border-2 border-white bg-white/80 p-3.5 lg:col-span-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h2 className="text-[13px] font-bold leading-none text-ink">Daily tokens</h2>
                  <p className="mt-1 text-[11px] leading-none text-ink/45">Compact trend — {days}d, per-day totals</p>
                </div>
                <span className="rounded-full bg-ink/[0.04] px-2 py-1 text-[11px] font-semibold tabular-nums text-ink/50">{data.daily.length} days</span>
              </div>
              {data.daily.length === 0 ? (
                <p className="mt-4 rounded-xl bg-ink/[0.03] px-3 py-6 text-center text-[11px] text-ink/40">No daily data.</p>
              ) : (
                <CompactArea points={data.daily.map((d) => ({ x: d.day.slice(5), y: d.total_tokens }))} />
              )}
              <p className="mt-2 text-[11px] text-ink/30">{insights?.growth !== undefined && insights.growth >= 0 ? "Progress is tracked daily — watch for flat lines indicating stalled tenants." : ""}</p>
            </div>

            <div className="rounded-2xl border-2 border-white bg-white/80 p-3.5 lg:col-span-2">
              <h2 className="text-[13px] font-bold leading-none text-ink">Top models</h2>
              <p className="mt-1 text-[11px] leading-none text-ink/45">By token share — where people get value</p>
              <div className="mt-3 space-y-2">
                {data.per_model.slice(0, 5).map((m) => (
                  <div key={m.model} className="group">
                    <div className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="truncate font-semibold text-ink" title={m.model}>{m.model.split(":").pop()}</span>
                      <span className="shrink-0 tabular-nums text-ink/50">{fmt(m.total_tokens)} · {m.calls}</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink/[0.06]">
                      <div className="h-full rounded-full bg-deep-violet transition-all group-hover:bg-violet-600" style={{ width: `${Math.max(3, (m.total_tokens / maxModel) * 100)}%` }} />
                    </div>
                  </div>
                ))}
                {data.per_model.length === 0 && <p className="text-[11px] text-ink/40">No model data.</p>}
                {data.per_model.length > 5 && <p className="pt-1 text-[11px] text-ink/35">+{data.per_model.length - 5} more models</p>}
              </div>
              {insights?.leader && (
                <p className="mt-3 rounded-xl bg-violet-50 px-2.5 py-2 text-[11px] leading-snug text-violet-800 ring-1 ring-violet-100">
                  Leader <b>{insights.leader.model.split(":").pop()}</b> drives {insights.leaderShare}% of tokens — ensure it stays fast & cheap.
                </p>
              )}
            </div>
          </div>

          {/* per tenant — compact table */}
          <div className="rounded-2xl border-2 border-white bg-white/80 p-3 sm:p-3.5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-[13px] font-bold leading-none text-ink">Tenants by progress</h2>
              <div className="flex items-center gap-2">
                <span className="hidden text-[11px] text-ink/35 sm:inline">{tenants.length} of {data.per_tenant.length} shown</span>
                <div className="relative">
                  <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink/30">
                    <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M15.5 15.5L19 19" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Filter email or id…"
                    className="w-48 rounded-xl border border-ink/[0.08] bg-white py-1.5 pl-8 pr-3 text-[11px] text-ink placeholder:text-ink/35 outline-none focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/10 sm:w-56"
                  />
                </div>
              </div>
            </div>

            <div className="mt-3 overflow-x-auto rounded-xl ring-1 ring-ink/[0.06]">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-ink/[0.02] text-left text-[10px] uppercase tracking-wide text-ink/40">
                    <th className="px-3 py-2 font-bold">Tenant</th>
                    <th className="px-2 py-2 font-bold">Tokens</th>
                    <th className="hidden px-2 py-2 font-bold sm:table-cell">Share</th>
                    <th className="px-2 py-2 text-right font-bold">Calls</th>
                    <th className="px-2 py-2 text-right font-bold">Avg</th>
                    <th className="px-3 py-2 text-right font-bold">Last active</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/[0.04] bg-white">
                  {tenants.slice(0, 20).map((t) => {
                    const isDormant = t.last_seen ? Date.now() - new Date(t.last_seen).getTime() > 7 * 86400 * 1000 : true;
                    const isTop = insights?.top1?.tenant_id === t.tenant_id;
                    return (
                      <tr key={t.tenant_id ?? t.email} className={`transition ${isDormant ? "bg-amber-50/30 hover:bg-amber-50/50" : "hover:bg-ink/[0.02]"}`}>
                        <td className="max-w-[220px] px-3 py-2">
                          <div className="flex items-center gap-1.5">
                            <span className={`h-2 w-2 shrink-0 rounded-full ${isDormant ? "bg-amber-400" : "bg-emerald-400"}`} aria-hidden title={isDormant ? "Dormant >7d" : "Active"} />
                            <span className={`truncate font-medium ${isTop ? "font-bold text-deep-violet" : "text-ink/80"}`} title={t.tenant_id ?? ""}>{t.email}</span>
                            {isTop && <span className="rounded-full bg-deep-violet px-1.5 py-0.5 text-[9px] font-bold uppercase text-white">Top</span>}
                          </div>
                        </td>
                        <td className="px-2 py-2 font-semibold tabular-nums text-ink">{fmt(t.total_tokens)}</td>
                        <td className="hidden px-2 py-2 sm:table-cell">
                          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-ink/[0.06]">
                            <div className="h-full rounded-full bg-deep-violet" style={{ width: `${Math.max(4, (t.total_tokens / maxTenant) * 100)}%` }} />
                          </div>
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-ink/60">{t.calls}</td>
                        <td className={`px-2 py-2 text-right tabular-nums ${t.avg_latency_ms > 3000 ? "font-bold text-amber-600" : "text-ink/60"}`}>{fmtMs(t.avg_latency_ms)}</td>
                        <td className="px-3 py-2 text-right">
                          <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${isDormant ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200" : "text-ink/50"}`}>
                            {t.last_seen ? new Date(t.last_seen).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                  {tenants.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-8 text-center text-ink/40">No usage in this period.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {tenants.length > 20 && <p className="mt-2 text-center text-[11px] text-ink/35">Showing top 20 by tokens · search to filter · full list {data.per_tenant.length}</p>}
            {data.per_tenant.length > 0 && (
              <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl bg-ink/[0.02] p-2.5 text-[11px] ring-1 ring-ink/[0.04]">
                <div className="text-center">
                  <p className="font-bold tabular-nums text-ink">{insights?.buckets.power ?? 0} power</p>
                  <p className="text-ink/40">≥10K</p>
                </div>
                <div className="text-center border-x border-ink/[0.06]">
                  <p className="font-bold tabular-nums text-ink">{insights?.buckets.active ?? 0} active</p>
                  <p className="text-ink/40">1K–10K</p>
                </div>
                <div className="text-center">
                  <p className="font-bold tabular-nums text-ink">{insights?.buckets.light ?? 0} light</p>
                  <p className="text-ink/40">&lt;1K</p>
                </div>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
