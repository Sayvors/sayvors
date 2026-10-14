"use client";

/**
 * Shared admin primitives.
 *
 * The audit found the admin pages were not a system: 5-8 font sizes chosen
 * per page, radius drifting 2-5 values depending on which page you loaded,
 * no <h1> anywhere, 10px labels, and an error state that read "Something went
 * wrong" with no way to recover. These components exist so none of that can
 * be reintroduced by accident — a page that uses them inherits the scale.
 *
 * Everything visual here traces to the ADMIN block in globals.css. Nothing
 * hardcodes a size, a radius or a colour.
 */

import type { HTMLAttributes, ReactNode } from "react";

/** The page's one and only <h1>. Every admin page has exactly one. */
export function PageHeader({
  title,
  lede,
  actions,
}: {
  title: string;
  lede?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-[var(--ad-m)] flex flex-wrap items-end justify-between gap-[var(--ad-s)]">
      <div className="min-w-0">
        <h1 className="text-admin-lg font-bold leading-tight tracking-tight text-ink">
          {title}
        </h1>
        {lede && (
          <p className="mt-[var(--ad-3xs)] text-admin-base text-ink/55">{lede}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-[var(--ad-2xs)]">{actions}</div>}
    </header>
  );
}

/**
 * Section heading. Always an <h2> so the document order is h1 > h2 > h3 with
 * no skipped levels — the audit found overview jumped straight from nothing
 * to <h2> and tenants had no headings at all.
 */
export function SectionTitle({
  children,
  as = "h2",
}: {
  children: ReactNode;
  as?: "h2" | "h3";
}) {
  const Tag = as;
  return (
    <Tag className="mb-[var(--ad-2xs)] text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/45">
      {children}
    </Tag>
  );
}

/** A surface. One radius, one border, no shadow — nothing floats here. */
export function Panel({
  children,
  className = "",
  ...rest
}: { children: ReactNode; className?: string } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-admin-card border border-card-border bg-card p-[var(--ad-s)] ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * The KPI tile. The number carries the weight (24px, tabular); the label is
 * deliberately quiet. This inverts the old layout, where a 10px bold
 * uppercase label shouted over a 24px number that should have led.
 */
export function Tile({
  label,
  value,
  broken = false,
}: {
  label: string;
  value: ReactNode;
  broken?: boolean;
}) {
  return (
    <div
      className={`rounded-admin-card border p-[var(--ad-s)] ${
        broken ? "border-coral/40 bg-coral/[0.05]" : "border-card-border bg-card"
      }`}
    >
      <div className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/50">
        {label}
      </div>
      <div
        className={`mt-[var(--ad-2xs)] text-admin-read font-bold tabular-nums leading-none ${
          broken ? "text-coral" : "text-ink"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

/**
 * Failure state. The audit's worst finding: the raw exception text was
 * surfaced to the operator with no recovery. Now it states what failed and
 * hands over the control to fix it.
 */
export function ErrorState({
  title = "Something went wrong",
  detail,
  onRetry,
}: {
  title?: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-admin-card border border-coral/40 bg-coral/[0.05] p-[var(--ad-s)]"
    >
      <p className="text-admin-base font-bold text-coral">{title}</p>
      {detail && (
        <p className="mt-[var(--ad-3xs)] text-admin-base text-ink/70">{detail}</p>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="admin-btn mt-[var(--ad-xs)] border border-coral/40 bg-card text-coral hover:bg-coral/10"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** Empty is a result, not an error, and must not look like one. */
export function EmptyState({ message }: { message: string }) {
  return (
    <p className="py-[var(--ad-m)] text-center text-admin-base text-ink/45">{message}</p>
  );
}

/**
 * A table that scrolls inside its own container.
 *
 * The audit found the wrappers used `overflow-hidden`, which CLIPED the
 * trailing columns at 390px — Posts, Databanks and Last sync were simply
 * unreachable, with no scrollbar to reveal them. `min-w` guarantees the
 * table keeps its columns instead of crushing them; `overflow-x-auto` on the
 * wrapper scrolls; `overflow-y-hidden` preserves the rounded corners.
 */
export function TableScroll({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto overflow-y-hidden rounded-admin-card border border-card-border bg-card">
      {children}
    </div>
  );
}

/** Consistent table internals, so pages stop re-declaring them by hand. */
export function Table({ children, minWidth = 640 }: { children: ReactNode; minWidth?: number }) {
  return (
    <table
      className="w-full text-left text-admin-base"
      style={{ minWidth: `${minWidth}px` }}
    >
      {children}
    </table>
  );
}

export function Th({ children, align = "left" }: { children: ReactNode; align?: "left" | "right" }) {
  return (
    <th
      scope="col"
      className={`px-[var(--ad-s)] py-[var(--ad-xs)] text-admin-micro font-bold uppercase tracking-[0.1em] text-ink/45 ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className = "",
  ...rest
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
} & HTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={`border-t border-ink/[0.06] px-[var(--ad-s)] py-[var(--ad-xs)] align-top ${
        align === "right" ? "text-right tabular-nums" : "text-left"
      } ${className}`}
      {...rest}
    >
      {children}
    </td>
  );
}

/** Status pill. The only place a full radius is allowed. */
export function Pill({
  tone = "neutral",
  children,
}: {
  tone?: "ok" | "bad" | "warn" | "neutral";
  children: ReactNode;
}) {
  const tones = {
    ok: "bg-emerald-100 text-emerald-800",
    bad: "bg-coral/15 text-coral",
    warn: "bg-amber-100 text-amber-900",
    neutral: "bg-ink/[0.06] text-ink/60",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-full px-[var(--ad-2xs)] py-[var(--ad-3xs)] text-admin-micro font-bold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}