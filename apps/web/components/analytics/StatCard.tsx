"use client";

import { ReactNode } from "react";

export function DeltaChip({ delta, suffix = "%" }: { delta: number | null; suffix?: string }) {
  if (delta === null || delta === undefined) {
    return <span className="text-[11px] font-medium text-ink/35">no prior data</span>;
  }
  const up = delta > 0;
  const flat = delta === 0;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
        flat
          ? "bg-ink/[0.05] text-ink/50"
          : up
            ? "bg-emerald/10 text-emerald"
            : "bg-coral/10 text-coral"
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
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
  delta?: number | null;
  deltaSuffix?: string;
  icon?: ReactNode;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm" aria-hidden>
        <div className="h-3 w-24 animate-pulse rounded bg-ink/[0.07]" />
        <div className="mt-3 h-7 w-16 animate-pulse rounded bg-ink/[0.07]" />
        <div className="mt-2 h-3 w-20 animate-pulse rounded bg-ink/[0.05]" />
      </div>
    );
  }
  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm transition hover:shadow-md hover:shadow-deep-violet/[0.06]">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] sm:text-[11px] font-semibold uppercase tracking-wide text-ink/55">{label}</p>
        {icon && (
          <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg ${accent ?? "bg-deep-violet/10 text-deep-violet"}`}>
            {icon}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <p className="text-[22px] font-bold text-ink">{value}</p>
        <DeltaChip delta={delta ?? null} suffix={deltaSuffix} />
      </div>
      {sub && <p className="text-[10px] text-ink/40">{sub}</p>}
    </div>
  );
}
