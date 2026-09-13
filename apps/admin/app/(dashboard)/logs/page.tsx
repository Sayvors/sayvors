"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface HealthService {
  name: string;
  kind: string;
  ok: boolean;
  latency_ms: number;
  detail: string;
  enabled: boolean;
  key_source: string;
}
interface HealthFailure {
  source: string;
  type: string;
  message: string;
  at: string | null;
}
interface Health {
  status: "ok" | "degraded" | "down";
  checked_at: string | null;
  uptime_seconds: number;
  probe: boolean;
  services: HealthService[];
  recent_failures: HealthFailure[];
}

function fmtUptime(s: number): string {
  if (!Number.isFinite(s) || s < 0) return "—";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff/60000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff/3600000)}h ago`;
  return d.toLocaleString();
}
function KindIcon({ kind, ok }: { kind: string; ok: boolean }) {
  const cls = `h-3.5 w-3.5 ${ok ? "text-white/90" : "text-white/80"}`;
  const k = kind.toLowerCase();
  if (k.includes("postgres") || k.includes("database")) return <svg viewBox="0 0 24 24" fill="none" className={cls} aria-hidden><ellipse cx="12" cy="7" rx="7" ry="3.5" stroke="currentColor" strokeWidth="1.6"/><path d="M5 7v7c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5V7" stroke="currentColor" strokeWidth="1.6"/><path d="M5 12c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5" stroke="currentColor" strokeWidth="1.6"/></svg>;
  if (k.includes("redis") || k.includes("cache")) return <svg viewBox="0 0 24 24" fill="none" className={cls} aria-hidden><rect x="4" y="5" width="16" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6"/><rect x="4" y="11" width="16" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" opacity="0.7"/><path d="M8 8h4M8 14h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>;
  if (k.includes("kafka") || k.includes("events")) return <svg viewBox="0 0 24 24" fill="none" className={cls} aria-hidden><rect x="3.5" y="6" width="17" height="12" rx="2" stroke="currentColor" strokeWidth="1.6"/><path d="M7 10h10M7 14h7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><circle cx="17.5" cy="10" r="1" fill="currentColor"/></svg>;
  if (k.includes("business")) return <svg viewBox="0 0 24 24" fill="none" className={cls} aria-hidden><rect x="4" y="4" width="16" height="16" rx="2.5" stroke="currentColor" strokeWidth="1.6"/><path d="M8 9h8M8 12h8M8 15h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>;
  // llm
  return <svg viewBox="0 0 24 24" fill="none" className={cls} aria-hidden><path d="M12 3l1.7 3.4 3.5.5-2.6 2.6.6 3.6L12 10.8 8.8 12.5l.6-3.6-2.6-2.6 3.5-.5L12 3z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>;
}

export default function AdminLogsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState(false);
  const [filter, setFilter] = useState<"all" | "working" | "broken" | "disabled" | "key" | "nokey">("all");
  const [q, setQ] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (probe: boolean) => {
    if (probe) setProbing(true); else setLoading(true);
    try {
      const data = await adminFetch<Health>(probe ? "/api/v1/admin/health?probe=true" : "/api/v1/admin/health");
      setHealth(data); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Load failed."); }
    finally { setLoading(false); setProbing(false); }
  }, []);

  useEffect(() => {
    void load(false);
    timer.current = setInterval(() => void load(false), 30000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [load]);

  const isAI = (s: HealthService) => s.name.startsWith("AI:");
  // Hide providers not in DB — only show DB-backed (key in DB) to match backend filter
  const baseServices = (health?.services ?? []).filter((s) => !isAI(s) || s.key_source === "database");
  const matchFilter = (s: HealthService) => {
    const f = q.trim().toLowerCase();
    if (f && !s.name.toLowerCase().includes(f) && !s.kind.toLowerCase().includes(f) && !s.detail.toLowerCase().includes(f)) return false;
    switch (filter) {
      case "working": return s.ok;
      case "broken": return !s.ok;
      case "key": return s.key_source === "database";
      default: return true;
    }
  };
  const services = baseServices.filter(matchFilter);
  const infra = services.filter((s) => !isAI(s));
  const ai = services.filter(isAI);
  const count = (fn: (s: HealthService) => boolean) => baseServices.filter(fn).length;

  const filters = [
    { key: "all", label: `All`, n: count(() => true) },
    { key: "working", label: `Healthy`, n: count((s) => s.ok) },
    { key: "broken", label: `Failing`, n: count((s) => !s.ok) },
    { key: "key", label: `With key`, n: count((s) => s.key_source === "database") },
  ] as const;

  const statusMeta = health?.status === "ok" ? { bg: "bg-emerald-500", label: "Healthy", desc: "All checks passing", dot: "bg-emerald-500", ring: "shadow-[0_0_0_6px_rgba(16,185,129,0.15)]" }
    : health?.status === "degraded" ? { bg: "bg-amber-500", label: "Degraded", desc: "Some services need attention", dot: "bg-amber-500", ring: "shadow-[0_0_0_6px_rgba(245,158,11,0.15)]" }
    : { bg: "bg-red-500", label: "Down", desc: "Core service unreachable", dot: "bg-red-500", ring: "shadow-[0_0_0_6px_rgba(239,68,68,0.15)]" };

  const insights = useMemo(() => {
    if (!health) return null;
    const total = baseServices.length;
    const ok = baseServices.filter((s) => s.ok).length;
    const failingInfra = baseServices.filter((s) => !isAI(s) && !s.ok).length;
    const recent = health.recent_failures.length;
    return { total, ok, missing: 0, failingInfra, recent, pct: total ? Math.round((ok/total)*100) : 0 };
  }, [health, baseServices]);

  return (
    <div className="space-y-4">
      {/* Header hero */}
      <div className="overflow-hidden rounded-[6px] border-2 border-white bg-white/85 shadow-sm">
        <div className="bg-gradient-to-r from-deep-violet/[0.06] via-violet-500/[0.04] to-sky-500/[0.05] px-4 py-4 sm:px-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h1 className="flex flex-wrap items-center gap-2 text-[18px] font-bold tracking-tight text-ink">
                Logs & health
                {health && (
                  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-white ${statusMeta.bg}`}>
                    <span className={`h-2 w-2 rounded-full bg-white`} aria-hidden /> {statusMeta.label}
                  </span>
                )}
                {health && <span className="hidden text-[11px] font-medium text-ink/40 sm:inline">· {insights?.ok}/{insights?.total} ok · {insights?.pct}%</span>}
              </h1>
              <p className="mt-1 max-w-[640px] text-[11px] leading-relaxed text-ink/50">
                Service liveness + the last 20 outbox/ingest failures. <span className="font-medium text-ink/60">{statusMeta.desc}</span>
                {health?.checked_at && <span className="text-ink/40"> · checked {fmtRelative(health.checked_at)} · {new Date(health.checked_at).toLocaleTimeString()}</span>}
                {health && <> · up {fmtUptime(health.uptime_seconds)}{health.probe ? " · live probe" : " · metadata only"}</>}
              </p>
              {insights && insights.missing > 0 && (
                <p className="mt-2 inline-flex rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-700 ring-1 ring-amber-200">
                  {insights.missing} AI providers missing keys — tenants see fewer models · <span className="hidden sm:inline">configure in LLMs</span>
                </p>
              )}
              {insights && insights.failingInfra > 0 && (
                <p className="mt-1.5 inline-flex rounded-full bg-red-50 px-2.5 py-1 text-[11px] font-bold text-red-700 ring-1 ring-red-200">
                  {insights.failingInfra} infra failing — triage first (DB/Redis/Kafka)
                </p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button onClick={() => void load(false)} disabled={loading} className="rounded-xl bg-white px-3 py-2 text-[12px] font-semibold text-ink/60 ring-1 ring-ink/[0.08] transition hover:bg-ink/[0.03] hover:text-ink disabled:opacity-50">
                {loading ? "Checking…" : "Refresh"}
              </button>
              <button
                onClick={() => void load(true)}
                disabled={probing || loading}
                title="Live probe hits Localith + each AI provider (free list calls)"
                className="rounded-xl bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-[#4a2575] disabled:opacity-50"
              >
                {probing ? "Probing…" : "Live check"}
              </button>
            </div>
          </div>
          {/* mini stats */}
          {health && (
            <div className="mt-4 grid gap-2 sm:grid-cols-4">
              {[
                { label: "Uptime", value: fmtUptime(health.uptime_seconds), sub: health.probe ? "live probe on" : "metadata only" },
                { label: "Services", value: `${insights?.ok}/${insights?.total}`, sub: `${insights?.pct}% healthy` },
                { label: "Infra failing", value: String(insights?.failingInfra ?? 0), sub: insights?.failingInfra ? "needs triage" : "all clear", tone: insights?.failingInfra ? "text-red-600" : "text-emerald-600" },
                { label: "Recent failures", value: String(health.recent_failures.length), sub: health.recent_failures.length ? "last 20" : "no recent" },
              ].map((c) => (
                <div key={c.label} className="rounded-[6px] bg-white px-3.5 py-3 ring-1 ring-ink/[0.06]">
                  <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{c.label}</p>
                  <p className={`mt-1 text-[15px] font-bold leading-none tabular-nums ${c.tone ?? "text-ink"}`}>{c.value}</p>
                  <p className="mt-1 text-[11px] leading-none text-ink/40">{c.sub}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {error ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
          <button onClick={() => void load(false)} className="mt-3 rounded-xl bg-deep-violet px-3 py-1.5 text-[12px] font-bold text-white">Retry</button>
        </div>
      ) : !health && loading ? (
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-[92px] animate-pulse rounded-[6px] border-2 border-white bg-white/60" />
          ))}
        </div>
      ) : health && (
        <>
          {/* toolbar */}
          <div className="flex flex-col gap-2.5 rounded-[6px] border-2 border-white bg-white/70 p-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-1.5">
              {filters.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key as any)}
                  aria-pressed={filter === f.key}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-bold transition ${filter === f.key ? "bg-deep-violet text-white shadow-sm" : "bg-white text-ink/60 ring-1 ring-ink/[0.06] hover:bg-ink/[0.03] hover:text-ink"}`}
                >
                  {f.label} <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${filter === f.key ? "bg-white/20 text-white" : "bg-ink/[0.06] text-ink/50"}`}>{f.n}</span>
                </button>
              ))}
            </div>
            <div className="relative">
              <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink/30"><circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.6"/><path d="M15.5 15.5L19 19" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter services…" className="w-48 rounded-xl border border-ink/[0.08] bg-white py-1.5 pl-8 pr-3 text-[11px] text-ink placeholder:text-ink/35 outline-none focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/10 sm:w-56"/>
            </div>
          </div>

          {/* Infra */}
          {infra.length > 0 && (
            <section>
              <h2 className="mb-2 flex items-center gap-2 px-1 text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                Infrastructure <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-bold tabular-nums text-ink/50 ring-1 ring-ink/10">{infra.length}</span>
              </h2>
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                {infra.map((s) => (
                  <div key={s.name} className={`relative overflow-hidden rounded-[6px] border-2 bg-white/85 p-3.5 shadow-sm transition hover:shadow-md ${s.ok ? "border-white" : "border-red-200 bg-red-50/30"}`}>
                    <div className={`absolute left-0 top-0 h-1 w-full ${s.ok ? "bg-emerald-500" : "bg-red-500"}`} aria-hidden />
                    <div className="flex items-start justify-between gap-2">
                      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${s.ok ? "bg-emerald-500" : "bg-red-500"} shadow-sm`}>
                        <KindIcon kind={s.kind} ok={s.ok} />
                      </span>
                      <span className={`rounded-full px-2 py-1 text-[10px] font-bold tabular-nums ring-1 ${s.ok ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-red-50 text-red-700 ring-red-200"}`}>{s.latency_ms}ms</span>
                    </div>
                    <p className="mt-2.5 flex items-center gap-2 text-[13px] font-bold leading-none text-ink">
                      <span className={`h-2 w-2 rounded-full ${s.ok ? "bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.15)]" : "bg-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.15)]"}`} aria-hidden /> {s.name}
                    </p>
                    <p className="mt-1 text-[11px] font-medium text-ink/40">{s.kind}</p>
                    <p className="mt-1.5 line-clamp-3 break-words text-[11px] leading-relaxed text-ink/60" title={s.detail}>{s.detail || (s.ok ? "Working" : "Not working")}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* AI */}
          {ai.length > 0 && (
            <section>
              <h2 className="mb-2 flex items-center gap-2 px-1 text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                AI providers <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-bold tabular-nums text-ink/50 ring-1 ring-ink/10">{ai.length}</span>
                <span className="hidden text-[11px] font-normal normal-case tracking-normal text-ink/30 sm:inline">· keys in DB = ready for tenants</span>
              </h2>
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {ai.map((s) => (
                  <div key={s.name} className={`relative overflow-hidden rounded-[6px] p-3.5 shadow-sm ring-1 transition ${s.ok ? "bg-white ring-ink/[0.06] hover:shadow-md" : s.key_source === "disabled" ? "bg-ink/[0.02] ring-ink/10 opacity-80" : "bg-amber-50/60 ring-amber-200"}`}>
                    <div className="flex items-center gap-2">
                      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${s.ok ? "bg-deep-violet text-white" : s.key_source==="disabled" ? "bg-ink/20 text-white" : "bg-amber-500 text-white"}`}>
                        <KindIcon kind={s.kind} ok={true} />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[12px] font-bold text-ink">{s.name.replace("AI:", "")}</span>
                      <span className={`h-2 w-2 shrink-0 rounded-full ${s.ok ? "bg-emerald-500" : "bg-red-500"}`} aria-hidden />
                      <span className="text-[10px] font-bold tabular-nums text-ink/40">{s.latency_ms}ms</span>
                    </div>
                    <p className="mt-2 line-clamp-2 break-words text-[11px] leading-relaxed text-ink/60" title={s.detail}>{s.detail}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {!s.enabled && <span className="rounded-full bg-ink/10 px-2 py-1 text-[10px] font-bold uppercase text-ink/50">disabled</span>}
                      {s.key_source === "database" && <span className="rounded-full bg-deep-violet/10 px-2 py-1 text-[10px] font-bold uppercase text-deep-violet">key in DB</span>}
                      {s.key_source === "none" && <span className="rounded-full bg-amber-100 px-2 py-1 text-[10px] font-bold uppercase text-amber-700">missing key</span>}
                      {s.key_source === "disabled" && <span className="rounded-full bg-ink/5 px-2 py-1 text-[10px] font-bold uppercase text-ink/40">off</span>}
                    </div>
                  </div>
                ))}
                {ai.length === 0 && <p className="col-span-full rounded-[6px] bg-white/60 p-6 text-center text-[11px] text-ink/40">No AI providers in this filter.</p>}
              </div>
            </section>
          )}

          {services.length === 0 && (
            <div className="rounded-[6px] border-2 border-white bg-white/60 p-8 text-center text-[12px] text-ink/40">
              No services match — clear search or switch filter.
              <button onClick={() => { setQ(""); setFilter("all"); }} className="ml-2 font-bold text-deep-violet hover:underline">Reset</button>
            </div>
          )}

          {/* Recent failures */}
          <section className="rounded-[6px] border-2 border-white bg-white/80 p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3">
              <h2 className="flex items-center gap-2 text-[13px] font-bold tracking-tight text-ink">
                Recent failures
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold tabular-nums ring-1 ${health.recent_failures.length ? "bg-red-50 text-red-700 ring-red-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"}`}>{health.recent_failures.length}</span>
                <span className="hidden text-[11px] font-normal text-ink/30 sm:inline">· last 20 · {health.probe ? "after probe" : "metadata only"}</span>
              </h2>
              <span className="hidden text-[11px] text-ink/30 sm:inline">Auto-refresh 30s · {fmtRelative(health.checked_at)}</span>
            </div>
            {health.recent_failures.length === 0 ? (
              <div className="mt-4 rounded-[6px] border border-dashed border-emerald-200 bg-emerald-50/50 p-8 text-center">
                <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500 text-white">✓</div>
                <p className="mt-2 text-[13px] font-bold text-emerald-700">No failures recorded</p>
                <p className="mx-auto mt-1 max-w-[420px] text-[11px] leading-relaxed text-emerald-700/70">Good sign — outbox and ingest are clear. Failures appear here for 20 most recent with source, type and time.</p>
              </div>
            ) : (
              <ul className="mt-4 space-y-2">
                {health.recent_failures.map((f, i) => (
                  <li key={`${f.source}-${f.type}-${i}`} className="flex gap-3 rounded-[6px] bg-ink/[0.02] p-3 ring-1 ring-ink/[0.04] transition hover:bg-white">
                    <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${f.source==="outbox"?"bg-amber-500":"bg-sky-500"}`} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 text-[12px] font-semibold text-ink">
                        <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide ring-1 ${f.source==="outbox"?"bg-amber-50 text-amber-700 ring-amber-200":"bg-sky-50 text-sky-700 ring-sky-200"}`}>{f.source}</span>
                        <span className="truncate">{f.type}</span>
                        <span className="ml-auto shrink-0 rounded-full bg-white px-2 py-1 text-[10px] font-medium tabular-nums text-ink/40 ring-1 ring-ink/10">{f.at ? fmtRelative(f.at) : "—"}</span>
                      </p>
                      {f.message && <p className="mt-1 break-words text-[11px] leading-relaxed text-ink/55">{f.message}</p>}
                      {f.at && <p className="mt-1 text-[10px] text-ink/30" title={f.at}>{new Date(f.at).toLocaleString()}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
