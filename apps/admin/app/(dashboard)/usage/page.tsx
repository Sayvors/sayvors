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

function AreaChart({ points }: { points: { x: string; y: number }[] }) {
  const W = 560;
  const H = 140;
  const PAD = 30;
  const max = Math.max(1, ...points.map((p) => p.y));
  const n = Math.max(1, points.length - 1);
  const px = (i: number) => PAD + (i / n) * (W - PAD * 2);
  const py = (v: number) => H - PAD - (v / max) * (H - PAD * 2);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
  const area = `${line} L${px(points.length - 1).toFixed(1)},${(H - PAD).toFixed(1)} L${PAD},${(H - PAD).toFixed(1)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full text-ink">
      {[0, 0.5, 1].map((f) => {
        const t = Math.round(max * f);
        return (
          <g key={f}>
            <line x1={PAD} x2={W - PAD} y1={py(t)} y2={py(t)} stroke="currentColor" strokeOpacity={0.08} />
            <text x={PAD - 5} y={py(t) + 3.5} textAnchor="end" fontSize={9} fill="currentColor" opacity={0.45}>
              {t >= 1000 ? `${(t / 1000).toFixed(1)}K` : t}
            </text>
          </g>
        );
      })}
      <path d={area} fill="#5b2d8e" opacity={0.12} />
      <path d={line} fill="none" stroke="#5b2d8e" strokeWidth={2} strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={px(i)} cy={py(p.y)} r={1.8} fill="#5b2d8e">
          <title>{`${p.x}: ${p.y.toLocaleString()} tokens`}</title>
        </circle>
      ))}
      <text x={PAD} y={H - 8} fontSize={9} fill="currentColor" opacity={0.45}>{points[0]?.x ?? ""}</text>
      <text x={W - PAD} y={H - 8} textAnchor="end" fontSize={9} fill="currentColor" opacity={0.45}>
        {points[points.length - 1]?.x ?? ""}
      </text>
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

  const daily = data?.daily ?? [];
  const perModel = data?.per_model ?? [];
  const tenants = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q || !data) return data?.per_tenant ?? [];
    return data.per_tenant.filter(
      (t) => t.email.toLowerCase().includes(q) || (t.tenant_id ?? "").toLowerCase().includes(q)
    );
  }, [data, search]);

  const maxTenant = Math.max(1, ...tenants.map((t) => t.total_tokens));

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Token Usage</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Global metering across all tenants — every LLM call with tokens and latency.
          </p>
        </div>
        <div className="flex gap-1.5">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={[
                "rounded-lg px-3 py-1.5 text-[12px] font-semibold",
                days === d ? "bg-deep-violet text-white" : "bg-white text-ink/60",
              ].join(" ")}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl border-2 border-white bg-white/60" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] text-ink/60">{error}</p>
          <button type="button" onClick={() => void load(days)} className="btn-primary mt-3">
            Retry
          </button>
        </div>
      ) : data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              { label: "Total tokens", value: fmt(data.totals.total_tokens) },
              { label: "LLM calls", value: String(data.totals.calls) },
              { label: "Active tenants", value: String(data.totals.active_tenants) },
            ].map((c) => (
              <div key={c.label} className="rounded-2xl border-2 border-white bg-white/80 p-4">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">{c.label}</div>
                <div className="mt-2 text-[22px] font-bold tabular-nums text-ink">{c.value}</div>
              </div>
            ))}
          </div>

          <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
            <h2 className="text-[16px] font-bold text-ink">Global daily trend</h2>
            <p className="text-[12px] text-ink/50">Tokens per day across all tenants.</p>
            {daily.length === 0 ? (
              <p className="mt-3 text-[12px] text-ink/40">No data.</p>
            ) : (
              <AreaChart points={daily.map((d) => ({ x: d.day.slice(5), y: d.total_tokens }))} />
            )}
          </div>

          <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-[16px] font-bold text-ink">Per tenant</h2>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search email or id…"
                className="input-field w-56"
              />
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-ink/[0.06] text-left text-ink/45">
                    <th className="px-3 py-2 font-semibold">Tenant</th>
                    <th className="px-3 py-2 font-semibold">Tokens</th>
                    <th className="px-3 py-2 font-semibold">Share</th>
                    <th className="px-3 py-2 text-right font-semibold">Calls</th>
                    <th className="px-3 py-2 text-right font-semibold">Avg latency</th>
                    <th className="px-3 py-2 text-right font-semibold">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((t) => (
                    <tr key={t.tenant_id ?? "none"} className="border-b border-ink/[0.03] last:border-0">
                      <td className="max-w-[260px] truncate px-3 py-2 font-medium text-ink/80" title={t.tenant_id ?? ""}>
                        {t.email}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-ink/70">{fmt(t.total_tokens)}</td>
                      <td className="px-3 py-2">
                        <div className="h-2 w-28 overflow-hidden rounded-full bg-ink/[0.06]">
                          <div
                            className="h-full rounded-full bg-deep-violet"
                            style={{ width: `${Math.max(2, (t.total_tokens / maxTenant) * 100)}%` }}
                          />
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-ink/70">{t.calls}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-ink/70">{fmtMs(t.avg_latency_ms)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-ink/50">
                        {t.last_seen ? new Date(t.last_seen).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                  {tenants.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-ink/40">
                        No usage in this period.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
            <h2 className="text-[16px] font-bold text-ink">Per model (global)</h2>
            <div className="mt-3 space-y-2.5">
              {perModel.map((m) => (
                <div key={m.model}>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="font-semibold text-ink">{m.model}</span>
                    <span className="tabular-nums text-ink/55">{fmt(m.total_tokens)} · {m.calls} calls</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink/[0.06]">
                    <div
                      className="h-full rounded-full bg-deep-violet"
                      style={{
                        width: `${Math.max(2, (m.total_tokens / Math.max(1, ...perModel.map((x) => x.total_tokens))) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
              {perModel.length === 0 && <p className="text-[12px] text-ink/40">No data.</p>}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
