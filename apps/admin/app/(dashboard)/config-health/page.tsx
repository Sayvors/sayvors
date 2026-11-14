"use client";

import { useEffect, useState } from "react";
import { fetchConfigHealth, type ConfigHealth } from "@/lib/admin-api";

/* Ops config health: which API keys/env flags are configured, without ever
 * exposing the values. Lets an operator spot a missing integration fast. */

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

export default function ConfigHealthPage() {
  const [data, setData] = useState<ConfigHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchConfigHealth()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load config health."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const missing = data?.groups.reduce(
    (n, g) => n + (Array.isArray(g.items) ? g.items.filter((i) => !i.ok).length : 0),
    0,
  ) ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Config health</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Which API keys and environment flags are configured. Values are never shown — only status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <span className={`rounded-full px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-wide ${
              missing === 0 ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
            }`}>
              {missing === 0 ? "All configured" : `${missing} missing/placeholder`}
            </span>
          )}
          <button onClick={load} disabled={loading} className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-50 ${FOCUS_RING}`}>
            {loading ? "Checking…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      {loading ? (
        <div className="grid gap-4 lg:grid-cols-2" aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="panel h-40 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {data?.groups.map((g) => (
            <div key={g.group} className="panel overflow-hidden">
              <div className="border-b border-[var(--ui-line)] px-4 py-3">
                <p className="text-[12px] font-bold text-ink">{g.group}</p>
                <p className="text-[10.5px] text-ink/45">
                  {g.items.filter((i) => i.ok).length}/{g.items.length} configured
                </p>
              </div>
              <ul className="divide-y divide-[var(--ui-line)]">
                {g.items.map((item) => (
                  <li key={item.key} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="min-w-0 truncate font-mono text-[11px] text-ink/80">{item.key}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide ${
                        item.ok
                          ? "bg-emerald-100 text-emerald-700"
                          : item.hint === "missing"
                            ? "bg-red-100 text-red-700"
                            : "bg-amber-100 text-amber-700"
                      }`}>
                        {item.ok ? "OK" : item.hint}
                      </span>
                      <span className="text-[10px] text-ink/40">{item.hint}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
