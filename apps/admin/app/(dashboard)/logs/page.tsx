"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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

function fmtUptime(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return "—";
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      aria-hidden
      className={`h-2.5 w-2.5 shrink-0 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
    />
  );
}

export default function AdminLogsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState(false);
  const [filter, setFilter] = useState<"all" | "working" | "broken" | "disabled" | "key" | "nokey">("all");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (probe: boolean) => {
    if (probe) setProbing(true);
    else setLoading(true);
    try {
      const data = await adminFetch<Health>(
        probe ? "/api/v1/admin/health?probe=true" : "/api/v1/admin/health"
      );
      setHealth(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    } finally {
      setLoading(false);
      setProbing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
    timer.current = setInterval(() => {
      void load(false);
    }, 30000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  const statusColor =
    health?.status === "ok"
      ? "bg-emerald-100 text-emerald-700"
      : health?.status === "degraded"
        ? "bg-amber-100 text-amber-700"
        : "bg-red-100 text-red-700";

  const isAI = (s: HealthService) => s.name.startsWith("AI:");
  const matchFilter = (s: HealthService) => {
    switch (filter) {
      case "working": return s.ok;
      case "broken": return !s.ok;
      case "disabled": return s.key_source === "disabled";
      case "key": return s.key_source === "database";
      case "nokey": return isAI(s) && s.key_source === "none";
      default: return true;
    }
  };
  const services = (health?.services ?? []).filter(matchFilter);
  const count = (fn: (s: HealthService) => boolean) => (health?.services ?? []).filter(fn).length;
  const filters = [
    { key: "all", label: `All (${count(() => true)})` },
    { key: "working", label: `Working (${count((s) => s.ok)})` },
    { key: "broken", label: `Not working (${count((s) => !s.ok)})` },
    { key: "disabled", label: `Disabled (${count((s) => s.key_source === "disabled")})` },
    { key: "key", label: `With key (${count((s) => s.key_source === "database")})` },
    { key: "nokey", label: `Missing key (${count((s) => isAI(s) && s.key_source === "none")})` },
  ] as const;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-[20px] font-bold text-ink">
            Logs
            {health && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${statusColor}`}>
                {health.status}
              </span>
            )}
          </h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Service status + recent failures
            {health?.checked_at && ` · checked ${new Date(health.checked_at).toLocaleTimeString()}`}
            {health && ` · API up ${fmtUptime(health.uptime_seconds)}`}
            {health && !health.probe && " · metadata checks (no live calls)"}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => void load(false)} disabled={loading} className="btn-secondary !px-3 !py-1.5 disabled:opacity-50">
            Refresh
          </button>
          <button
            onClick={() => void load(true)}
            disabled={probing || loading}
            title="Hit Localith and each AI provider live (free list calls)"
            className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
          >
            {probing ? "Probing…" : "Live check"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
        </div>
      ) : !health && loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-hidden>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl border-2 border-white bg-white/60" />
          ))}
        </div>
      ) : (
        health && (
          <>
            <div className="flex gap-1 overflow-x-auto rounded-xl bg-ink/[0.03] p-1">
              {filters.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold transition ${
                    filter === f.key ? "bg-white text-deep-violet shadow-sm" : "text-ink/45 hover:text-ink/70"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {services.length === 0 ? (
                <p className="col-span-full rounded-2xl border-2 border-white bg-white/80 p-8 text-center text-[12px] text-ink/40">
                  Nothing in this category.
                </p>
              ) : (
                services.map((s) => (
                <div key={s.name} className="rounded-2xl border-2 border-white bg-white/80 p-4">
                  <p className="flex items-center gap-2 text-[13px] font-bold text-ink">
                    <Dot ok={s.ok} />
                    {s.name}
                    <span className="ml-auto text-[11px] font-medium tabular-nums text-ink/40">
                      {s.latency_ms}ms
                    </span>
                  </p>
                  <p className="mt-1 text-[11px] text-ink/45">{s.kind}</p>
                  <p className="mt-1 break-words text-[12px] text-ink/70">{s.detail || (s.ok ? "Working" : "Not working")}</p>
                  {!s.enabled && (
                    <p className="mt-1 text-[10px] font-bold uppercase tracking-wide text-ink/35">disabled by admin</p>
                  )}
                  {s.key_source === "database" && (
                    <p className="mt-1 text-[10px] font-bold uppercase tracking-wide text-deep-violet/60">key in database</p>
                  )}
                </div>
                ))
              )}
            </div>

            <section className="rounded-2xl border-2 border-white bg-white/80 p-5">
              <h2 className="mb-3 text-[14px] font-bold text-ink">
                Recent failures
                <span className="ml-2 text-[11px] font-medium text-ink/40">{health.recent_failures.length}</span>
              </h2>
              {health.recent_failures.length === 0 ? (
                <p className="text-[12px] text-emerald-600">No failures recorded. Good sign.</p>
              ) : (
                <ul className="space-y-2">
                  {health.recent_failures.map((f, i) => (
                    <li key={`${f.source}-${f.type}-${i}`} className="rounded-xl bg-ink/[0.03] p-3">
                      <p className="flex flex-wrap items-center gap-2 text-[12px] font-semibold text-ink">
                        <span className="rounded bg-ink/[0.05] px-1.5 py-0.5 text-[10px] font-bold uppercase text-ink/50">
                          {f.source}
                        </span>
                        {f.type}
                        <span className="ml-auto text-[10px] font-normal text-ink/35">
                          {f.at ? new Date(f.at).toLocaleString() : ""}
                        </span>
                      </p>
                      {f.message && <p className="mt-1 break-words text-[11px] text-ink/55">{f.message}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )
      )}
    </div>
  );
}
