"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchSpecialTenants, type TenantSubscriptionRow } from "@/lib/billing-api";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function fmtGranted(iso: string | null): string {
  if (!iso) return "no expiry";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

/**
 * Tenants whose features differ from their plan.
 *
 * This list is the audit trail of hand-crafted entitlements: every row is a
 * tenant an admin explicitly customised, and clearing the overrides on the
 * tenant page removes it again.
 */
export default function SpecialListPage() {
  const [rows, setRows] = useState<TenantSubscriptionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchSpecialTenants()
      .then((data) => setRows(data))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the Special list."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const totalOverrides = rows.reduce((sum, r) => sum + Object.keys(r.features_override).length, 0);

  return (
    <div className="space-y-4">
      <div className="admin-rise flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink/40">Sayvors · Admin</p>
          <h1 className="mt-1 text-[22px] font-bold tracking-tight text-ink">Special list</h1>
          <p className="mt-1.5 max-w-[680px] text-[14px] font-medium leading-relaxed text-ink sm:text-[15px]">
            {loading ? (
              "Loading customised tenants…"
            ) : rows.length === 0 ? (
              "No tenant has per-feature overrides. Everybody inherits their plan exactly."
            ) : (
              <>
                <b className="font-bold text-deep-violet">{rows.length} tenant{rows.length === 1 ? "" : "s"}</b>{" "}
                with hand-set features · {totalOverrides} override{totalOverrides === 1 ? "" : "s"} total
              </>
            )}
          </p>
        </div>
        <button
          onClick={load}
          className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div role="alert" className="rounded-[2px] border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] leading-relaxed text-amber-800">
          {error} <button onClick={load} className={`ml-1 font-bold underline ${FOCUS_RING}`}>Retry</button>
        </div>
      ) : loading ? (
        <div className="grid gap-2" aria-hidden aria-label="Loading special list">
          {[1, 2, 3].map((i) => <div key={i} className="h-16 animate-pulse rounded-[2px] bg-ink/[0.04]" />)}
        </div>
      ) : rows.length === 0 ? (
        <div className="panel p-10 text-center">
          <p className="text-[14px] font-bold text-ink">Nobody is special yet</p>
          <p className="mx-auto mt-1 max-w-[440px] text-[12px] leading-relaxed text-ink/45">
            Open a tenant, click the Plan card, and change a feature. That tenant appears here until the
            overrides are cleared.
          </p>
          <Link
            href="/tenants"
            className={`mt-4 inline-flex rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white hover:bg-deep-violet/90 ${FOCUS_RING}`}
          >
            Go to tenants
          </Link>
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <div className="hidden border-b border-[var(--ui-line)] px-4 py-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 sm:grid sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2.2fr)_auto] sm:gap-3">
            <span>Tenant</span>
            <span>Plan</span>
            <span>Overrides</span>
            <span className="sr-only">Open</span>
          </div>
          <ul>
            {rows.map((r) => {
              const keys = Object.entries(r.features_override);
              return (
                <li key={r.id} className="border-b border-[var(--ui-line)] last:border-b-0">
                  <Link
                    href={`/tenants/${encodeURIComponent(r.tenant_id)}`}
                    className={`grid gap-2 px-4 py-3 transition hover:bg-ink/[0.02] sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2.2fr)_auto] sm:items-center sm:gap-3 ${FOCUS_RING}`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[12.5px] font-bold text-ink">{r.email ?? r.tenant_id}</span>
                      <span className="block truncate text-[10.5px] tabular-nums text-ink/35">{r.tenant_id}</span>
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[12px] font-semibold text-ink/70">{r.plan_name ?? "—"}</span>
                      <span className="block truncate text-[10.5px] text-ink/35">{r.plan_slug ?? ""}</span>
                    </span>
                    <span className="flex flex-wrap gap-1">
                      {keys.map(([key, value]) => (
                        <span
                          key={key}
                          className={`rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ${
                            value
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                              : "bg-red-50 text-red-700 ring-red-200"
                          }`}
                          title={`${key}: ${value ? "forced on" : "forced off"}`}
                        >
                          {key} {value ? "on" : "off"}
                        </span>
                      ))}
                    </span>
                    <span className="flex items-center justify-between gap-3 sm:justify-end">
                      <span className="text-[10.5px] text-ink/35">
                        {r.granted_by ? `by ${r.granted_by}` : ""} · {fmtGranted(r.granted_until)}
                      </span>
                      <span className="text-[11px] font-bold text-deep-violet">Open →</span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-ink/25">
        Overrides live on the subscription, not the plan — changing one tenant never touches another.
      </p>
    </div>
  );
}
