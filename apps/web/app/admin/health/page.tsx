"use client";

import { useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";

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
  status: string;
  checked_at: string | null;
  uptime_seconds: number;
  services: HealthService[];
  recent_failures: HealthFailure[];
}

export default function AdminHealthPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    adminFetch<Health>("/api/v1/admin/health")
      .then(setHealth)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load health."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading && !health) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  const up = (health?.uptime_seconds ?? 0);
  const uptime = up > 86400
    ? `${Math.floor(up / 86400)}d ${Math.floor((up % 86400) / 3600)}h`
    : `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m`;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${health?.status === "ok" ? "bg-emerald-100 text-emerald-700" : "bg-coral/15 text-coral"}`}>
            {health?.status ?? "unknown"}
          </span>
          <span className="text-[12px] text-ink/50">uptime {uptime}</span>
        </div>
        <button onClick={load} disabled={loading} className="rounded-lg border border-ink/10 px-3 py-1.5 text-[11px] font-bold text-ink/60 disabled:opacity-40">
          {loading ? "Checking…" : "Re-check now"}
        </button>
      </div>
      {error && <p className="rounded-xl bg-coral/10 px-4 py-3 text-[12px] font-medium text-coral">{error}</p>}

      <div className="overflow-hidden rounded-2xl border border-white bg-white/80">
        <table className="w-full text-left text-[12.5px]">
          <thead>
            <tr className="border-b border-ink/[0.06] text-[10px] font-bold uppercase tracking-[0.1em] text-ink/40">
              <th className="px-4 py-3">Service</th>
              <th className="px-4 py-3">Kind</th>
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3 text-right">Latency</th>
              <th className="px-4 py-3">Detail</th>
            </tr>
          </thead>
          <tbody>
            {(health?.services ?? []).map((s) => (
              <tr key={s.name} className="border-b border-ink/[0.04]">
                <td className="px-4 py-3 font-semibold text-ink">{s.name}</td>
                <td className="px-4 py-3 text-ink/55">{s.kind}</td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${s.ok ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
                    {s.ok ? "UP" : "DOWN"}
                  </span>
                  {!s.enabled && <span className="ml-1.5 text-[10px] text-ink/35">(disabled)</span>}
                  {s.key_source && s.key_source !== "none" && <span className="ml-1.5 text-[10px] text-ink/35">key: {s.key_source}</span>}
                </td>
                <td className="px-4 py-3 text-right text-ink/55">{s.latency_ms ? `${s.latency_ms}ms` : "—"}</td>
                <td className="max-w-xs truncate px-4 py-3 text-ink/45" title={s.detail}>{s.detail || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="rounded-2xl border border-white bg-white/80 p-4">
        <h2 className="text-[13px] font-bold uppercase tracking-wide text-ink/50">Recent failures</h2>
        {(health?.recent_failures ?? []).length === 0 ? (
          <p className="mt-2 text-[12px] text-emerald-600 font-medium">None recorded.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {(health?.recent_failures ?? []).map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-[12.5px]">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                <span>
                  <span className="font-semibold text-ink">{f.source}</span> <span className="text-ink/45">({f.type})</span>
                  {f.message && <span className="block text-ink/60">{f.message.slice(0, 160)}</span>}
                  {f.at && <span className="block text-[10px] text-ink/35">{new Date(f.at).toLocaleString()}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
