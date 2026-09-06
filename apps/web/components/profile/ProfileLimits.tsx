"use client";

import type { UsageItem } from "@/lib/api-profile";

const BAR = [
  "from-deep-violet to-magenta",
  "from-magenta to-coral",
  "from-sky-400 to-blue-500",
  "from-emerald-400 to-emerald-600",
];

export default function ProfileLimits({
  items,
  cached,
  loading,
  onRefresh,
}: {
  items: UsageItem[];
  cached: boolean;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <section aria-label="Usage" className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-[14px] font-bold text-ink">Usage</h3>
          <p className="text-[11px] text-ink/45">
            Live from your workspace{cached ? " · cached" : ""}.
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="rounded-lg border border-ink/15 px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:border-deep-violet/40 hover:text-deep-violet disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {loading && items.length === 0 ? (
        <div className="space-y-4" aria-label="Loading usage">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-ink/[0.05]" />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item, i) => (
            <div key={item.label}>
              <div className="mb-1.5 flex items-baseline justify-between gap-2">
                <span className="text-[12px] font-semibold text-ink">{item.label}</span>
                <span className="text-[11px] tabular-nums text-ink/45">
                  {item.used.toLocaleString()} / {item.total.toLocaleString()} {item.unit}
                </span>
              </div>
              <div
                className="h-2 w-full overflow-hidden rounded-full bg-ink/[0.07]"
                role="progressbar"
                aria-valuenow={Math.round(item.percent)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${item.label} usage`}
              >
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${BAR[i % BAR.length]} transition-all duration-500`}
                  style={{ width: `${Math.min(item.percent, 100)}%` }}
                />
              </div>
              <p className="mt-1 text-[10px] tabular-nums text-ink/35">{item.percent}% used</p>
            </div>
          ))}
          {items.length === 0 && !loading && (
            <p className="text-[12px] text-ink/45">No usage data yet.</p>
          )}
        </div>
      )}
    </section>
  );
}
