"use client";

import { ReactNode } from "react";

export function DeltaChip({ delta, suffix = "%", noPriorData = "no prior data" }: { delta: number | null; suffix?: string; noPriorData?: string }) {
  if (delta === null || delta === undefined) {
    return <span className="text-[11px] font-medium text-[var(--ui-ink-2)]">{noPriorData}</span>;
  }
  const up = delta > 0;
  const flat = delta === 0;
  // No hue (needs the .team-ui ancestor for the --ui-* vars): "worse" inverts
  // to ink, "better" sits on sunken, "flat" dims — same chips as MessagingSection.
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-[2px] px-2 py-0.5 text-[11px] font-bold tabular-nums ${
        flat
          ? "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]"
          : up
            ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
            : "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
      }`}
    >
      {!flat && (
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2.5 w-2.5 ${up ? "" : "rotate-180"}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {Math.abs(delta)}{suffix}
    </span>
  );
}

export function StatCard({
  label,
  value,
  sub,
  accent,
  delta,
  deltaSuffix,
  icon,
  loading,
  noPriorData,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
  delta?: number | null;
  deltaSuffix?: string;
  icon?: ReactNode;
  loading?: boolean;
  noPriorData?: string;
}) {
  if (loading) {
    return (
      <div className="ui-card p-4" aria-hidden>
        <div className="h-3 w-24 animate-pulse rounded bg-[var(--ui-sunken)]" />
        <div className="mt-3 h-7 w-16 animate-pulse rounded bg-[var(--ui-sunken)]" />
        <div className="mt-2 h-3 w-20 animate-pulse rounded bg-[var(--ui-sunken)]" />
      </div>
    );
  }
  return (
    <div className="ui-card p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] sm:text-[11px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">{label}</p>
        {icon && (
          <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-[2px] ${accent ?? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
            {icon}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <p className="text-[22px] font-bold text-[var(--ui-ink)]">{value}</p>
        <DeltaChip delta={delta ?? null} suffix={deltaSuffix} noPriorData={noPriorData} />
      </div>
      {sub && <p className="text-[10px] text-[var(--ui-ink-2)]">{sub}</p>}
    </div>
  );
}
