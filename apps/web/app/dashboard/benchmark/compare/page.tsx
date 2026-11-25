"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import LogoLoader from "@/components/LogoLoader";
import { apiFetch } from "@/lib/api-rag";
import {
  fetchComparison,
  fetchHistory,
  fetchReviewThemes,
  fetchReviews,
  fetchSavedPlaces,
  normalizeCompareRange,
  retryReviewThemes,
  RANGE_DAYS,
  subjectKey,
  type CompareRange,
  type ComparisonSubject,
  type HistoryPoint,
  type SavedPlace,
  type SubjectReviews,
} from "@/lib/api-benchmark";
import ComparePicker, {
  MAX_COMPETITORS,
  type CompareSelection,
} from "@/components/benchmark/ComparePicker";
import TrendChart from "@/components/benchmark/TrendChart";
import NorthStarCard from "@/components/benchmark/NorthStarCard";
import DistributionStrip from "@/components/benchmark/DistributionStrip";
import OwnScorecards from "@/components/benchmark/OwnScorecards";
import ReviewResponseTable from "@/components/benchmark/ReviewResponseTable";
import SentimentVelocityBars from "@/components/benchmark/SentimentVelocityBars";
import AiSummaryCard from "@/components/benchmark/AiSummaryCard";
import BaselineAlert from "@/components/benchmark/BaselineAlert";
import CompletenessCard from "@/components/benchmark/CompletenessCard";
import FixFirstTickets from "@/components/benchmark/FixFirstTickets";
import ReviewKeywords from "@/components/benchmark/ReviewKeywords";
import { queryKeys } from "@/lib/query-keys";
import {
  defaultCompareMain,
  sortCompareChannels,
  type CompareChannelOption,
} from "@/lib/benchmark-selection";
import VerificationBadge from "@/components/shared/VerificationBadge";
import {
  formatGap,
  formatPercent,
  formatRating,
  type GapUnit,
} from "@/lib/benchmark-format";
import {
  getMetricRows,
  type BenchmarkMetricRow,
} from "@/lib/benchmark-rows";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";
const REVIEW_THEME_POLL_MS = 3000;

type MetricKey = BenchmarkMetricRow["key"];
type FactKey = keyof ComparisonSubject["facts"];

interface Row<T extends string> {
  key: T;
  label: string;
  render: (subject: ComparisonSubject, subjects: ComparisonSubject[]) => ReactNode;
  /** Present only for rows that can be won; drives the per-row highlight. */
  value?: (subject: ComparisonSubject) => number | null;
  /**
   * Overrides `value` for the color comparison only. Use when the displayed
   * value is blank for "no data" but zero is a real measurement — e.g. an
   * average rating where Google gives no rating and we show "—".
   */
  tierValue?: (subject: ComparisonSubject) => number | null;
  higherIsBetter?: boolean;
  /** Unit used by the signed gap chip beneath this row's value. */
  gapUnit?: GapUnit;
}

type PeriodKey =
  | "period_reviews"
  | "period_avg_rating"
  | "rating_change";

/**
 * The period table answers "what changed in this window", never re-labels a
 * lifetime number as a window number. Saved places compute it from snapshot
 * history plus today's live values; own locations from their stored reviews.
 */
function getPeriodRows(c: Record<string, any>): Row<PeriodKey>[] {
  return [
    { key: "period_reviews", label: c.reviewsAdded, value: (s) => s.metrics.period_reviews, gapUnit: "count", render: (s) => num(s.metrics.period_reviews) },
    { key: "period_avg_rating", label: c.averageRatingInPeriod, value: (s) => s.metrics.period_avg_rating, gapUnit: "rating", render: (s) => s.metrics.period_avg_rating == null ? "—" : formatRating(s.metrics.period_avg_rating) },
    { key: "rating_change", label: c.ratingChange, value: (s) => s.metrics.rating_change, gapUnit: "rating", render: (s) => signed(s.metrics.rating_change) },
  ];
}

type RangeStatus = "ready" | "coming_soon";

function getRangeOptions(c: Record<string, any>): { value: CompareRange; label: string; title: string; status: RangeStatus }[] {
  return [
    { value: "live", label: c.live, title: c.liveTitle, status: "ready" },
    { value: "30d", label: c.days30, title: c.days30Title, status: "ready" },
    { value: "90d", label: c.days90, title: c.days90Title, status: "ready" },
    { value: "365d", label: c.year1, title: c.year1Title, status: "ready" },
  ];
}

/** Unsupported or missing ranges fall back to Live. */

function getFactRows(c: Record<string, any>): Row<FactKey>[] {
  return [
    { key: "positive_pct", label: c.positiveSentiment, value: (s) => s.facts.positive_pct, higherIsBetter: true, gapUnit: "percent", render: (s) => pct(s.facts.positive_pct) },
    { key: "negative_pct", label: c.negativeSentiment, value: (s) => s.facts.negative_pct, higherIsBetter: false, gapUnit: "percent", render: (s) => pct(s.facts.negative_pct) },
    { key: "branch", label: c.branchLocation, render: (s) => s.facts.branch ?? "—" },
    { key: "services", label: c.services, render: (s, all) => serviceChips(s.facts.services, all) },
    { key: "top_problems", label: c.topProblems, render: (s) => chips(s.facts.top_problems) },
    { key: "named_team", label: c.namedTeam, render: (s) => namedTeam(s.facts.named_team) },
  ];
}

/**
 * Overlap-level colors for the Services row. Green means the service is
 * carried by everyone in the table (or by four or more), blue by two or
 * three, red when no other business has it — so you can scan a row and see
 * which services the businesses actually share.
 */
const SERVICE_LEVEL_COLORS: Record<ServiceLevel, string> = {
  shared: "#10b981",
  second: "#0ea5e9",
  unique: "#DC2626",
};

function serviceOverlapLevel(count: number, total: number): ServiceLevel {
  if (count >= 4) return "shared";
  if (count === 2 || count === 3) return "second";
  return "unique";
}

type ServiceLevel = "shared" | "second" | "unique";

/**
 * Service chips colored by how many businesses in the table carry each
 * service: green when widely carried, blue when only two or three do, red
 * when it is a lone feature. Duplicates within one business are collapsed.
 */
function serviceChips(
  services: string[] | undefined,
  subjects: ComparisonSubject[]
): ReactNode {
  const list = services ?? [];
  if (!list.length) return <span className="text-[#8A8496]">—</span>;
  const total = subjects.filter((subject) => subject.available).length;
  const counts = new Map<string, number>();
  for (const subject of subjects) {
    if (!subject.available) continue;
    for (const name of new Set(subject.facts.services ?? [])) {
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
  }
  const seen = new Set<string>();
  return (
    <span className="flex flex-wrap gap-1">
      {list.map((name) => {
        if (seen.has(name)) return null;
        seen.add(name);
        const level = serviceOverlapLevel(counts.get(name) ?? 0, total);
        return (
          <span
            key={name}
            style={{ backgroundColor: SERVICE_LEVEL_COLORS[level], color: "#FFFFFF" }}
            className="rounded-[8px] px-1.5 py-0.5 text-[10px] font-semibold"
          >
            {name}
          </span>
        );
      })}
    </span>
  );
}

function num(value: number | null | undefined, suffix = ""): string {
  return value == null ? "—" : `${value}${suffix}`;
}

function pct(value: number | null | undefined): string {
  return formatPercent(value);
}

/** A rating movement: sign is the message, so keep it visible. */
function signed(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value === 0) return "0.00";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

type CellTier = "best" | "good" | "worst" | "empty";

/**
 * Cell backgrounds per tier, with the foreground chosen for contrast against
 * that background: white on the Deep Violet/Magenta/Coral accents, ink on the
 * light "empty" tint.
 */
const CELL_COLORS: Record<CellTier, { bg: string; fg: string }> = {
  best: { bg: "#3D1D6E", fg: "#FFFFFF" },
  good: { bg: "#B0338A", fg: "#FFFFFF" },
  worst: { bg: "#FF4F6E", fg: "#FFFFFF" },
  empty: { bg: "#E8E6EC", fg: "#14101F" },
};

/**
 * The tier a value's cell gets: deep violet when it is the leader of the row,
 * coral when it is the worst, magenta in between. "Empty" is a distinct gray —
 * a cell that shows `—` is one we genuinely don't know (e.g. Google does not
 * release the number), not one that scored zero.
 */
function cellTier<T extends string>(
  row: Row<T>,
  subjects: ComparisonSubject[],
  subject: ComparisonSubject,
  display: number | null
): CellTier {
  const select = row.tierValue ?? row.value;
  if (!subject.available || !select) return "empty";
  const value = select(subject);
  if (value == null) return "empty";
  const values = subjects
    .filter((s) => s.available && select)
    .map((s) => select(s))
    .filter((v): v is number => v != null);
  if (values.length <= 1) return "best";
  const higherIsBetter = row.higherIsBetter !== false;
  const best = higherIsBetter ? Math.max(...values) : Math.min(...values);
  const worst = higherIsBetter ? Math.min(...values) : Math.max(...values);
  if (value === best) return "best";
  if (value === worst) return "worst";
  return "good";
}

function ownerOnly(subject: ComparisonSubject, value: number | null): ReactNode {
  // Google releases views and calls only to the listing's owner, so a
  // competitor column can never have them. The cell renders "—" (the td
  // carries the empty-tier colors).
  if (subject.kind === "saved") {
    return <span>—</span>;
  }
  return num(value);
}

function chips(items: string[] | undefined): ReactNode {
  if (!items?.length) return <span className="text-[#8A8496]">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((item) => (
        <span
          key={item}
          className="rounded-[8px] bg-[#F4F2F7] px-1.5 py-0.5 text-[10px] font-semibold text-[#3B2D5E]"
        >
          {item}
        </span>
      ))}
    </span>
  );
}

function namedTeam(members: ComparisonSubject["facts"]["named_team"]): ReactNode {
  if (!members.length) return <span className="text-[#8A8496]">—</span>;
  return (
    <span className="flex flex-col gap-0.5">
      {members.map((member) => (
        <span key={member.name} className="text-[10px] leading-snug">
          <strong className="font-bold text-[#14101F]">{member.name}</strong>
          <span className="text-[#3B2D5E]"> · {member.mentions}</span>
        </span>
      ))}
    </span>
  );
}

/**
 * Gap chip: how this business differs from the tenant's own column.
 * Signed diff, colored by whether the direction helps (row-defined).
 */
function gapChip(
  value: number | null,
  mainValue: number | null,
  higherIsBetter: boolean,
  unit: GapUnit
): { text: string; className: string } | null {
  if (value == null || mainValue == null || value === mainValue) return null;
  if (!Number.isFinite(value) || !Number.isFinite(mainValue)) return null;
  const diff = value - mainValue;
  const text = formatGap(diff, unit);
  if (!text) return null;
  const helps = higherIsBetter ? diff > 0 : diff < 0;
  return {
    text,
    className: helps
      ? "bg-[#E7F6EC] text-[#116631]"
      : "bg-[#FDE8EC] text-[#B3123A]",
  };
}

/**
 * One table per fact group, in the shape the comparison is read in:
 * `Reviews total | 300 | 500 | 500 | 500 | 500 | 500`.
 *
 * The label column is sticky so the fact name stays readable while the six
 * business columns scroll horizontally on a narrow screen.
 *
 * Drill-down: when `onDrillDown` is set, a cell colored as the row's worst
 * tier becomes a button — the one column that trails the row is exactly the
 * one whose reviews explain why.
 */
function MatrixTable<T extends string>({
  title,
  description,
  rows,
  subjects,
  mainKey,
  onDrillDown,
  drillLoading = false,
}: {
  title: string;
  description?: string;
  rows: Row<T>[];
  subjects: ComparisonSubject[];
  mainKey: string | null;
  onDrillDown?: (subject: ComparisonSubject) => void;
  /** Reviews behind the drill-down still loading: clicks may no-op, so the cursor shows progress instead of a ready pointer. */
  drillLoading?: boolean;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const c = t.benchmark.compare;
  // On small screens the six business columns become one dropdown: the table
  // shows the fact rows for the selected business only.
  const [mobileIndex, setMobileIndex] = useState(0);

  /**
   * Props that turn a worst-tier cell's nested element into an accessible
   * drill-down button. The table cell itself stays a plain cell so screen
   * readers keep walking the table; this spread goes on the interactive
   * element inside it (a native button on desktop, a role-button span on
   * mobile).
   */
  function drillProps(row: Row<T>, subject: ComparisonSubject) {
    const interactive = onDrillDown != null && subject.available;
    if (!interactive) return {};
    return {
      role: "button" as const,
      tabIndex: 0,
      title: b.drillDownHint,
      "aria-label": `${row.label} · ${subject.name ?? subject.key} — ${b.drillDownHint}`,
      onClick: () => onDrillDown?.(subject),
      onKeyDown: (event: ReactKeyboardEvent) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onDrillDown?.(subject);
        }
      },
    };
  }

  /** Drill cursor reflects readiness: reviews still loading → progress. */
  function drillCursorClass(drillable: boolean): string {
    if (!drillable) return "";
    return drillLoading ? "cursor-progress" : "cursor-pointer";
  }

  return (
    <section className="mt-4 overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white">
      <div className="border-b border-[var(--ui-line)] px-3 py-2">
        <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{title}</h2>
        {description ? <p className="mt-0.5 text-[10px] text-[#3B2D5E]">{description}</p> : null}
      </div>

      {/* Mobile: pick the business column to inspect. */}
      <div className="flex items-center gap-2 border-b border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 md:hidden">
        <label htmlFor={`mobile-col-${title}`} className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
          {c.business}
        </label>
        <select
          id={`mobile-col-${title}`}
          value={mobileIndex}
          onChange={(event) => setMobileIndex(Number(event.target.value))}
          className="min-w-0 flex-1 rounded-[8px] border border-[var(--ui-line)] bg-white px-2 py-1.5 text-[11px] font-semibold text-[#14101F]"
        >
          {subjects.map((subject, index) => (
            <option key={subject.key} value={index}>
              {subject.name || (subject.kind === "own" ? c.yourLocation : c.savedBusiness)}
            </option>
          ))}
        </select>
      </div>

      {/* Mobile: one business column, stacked as a fact list. */}
      <div className="md:hidden">
        {subjects[mobileIndex] ? (
          <ul>
            {rows.map((row) => {
              const subject = subjects[mobileIndex];
              const value = subject.available && row.value ? row.value(subject) : null;
              const tier = cellTier(row, subjects, subject, value);
              const drillable = tier === "worst" && subject.available && onDrillDown != null;
              return (
                <li key={row.key} className="flex items-center justify-between gap-2 border-b border-[var(--ui-line)] px-3 py-2 last:border-b-0">
                  <span className="text-[11px] font-semibold text-[#14101F]">{row.label}</span>
                  <span
                    className={`min-w-0 flex-1 text-right text-[12px] font-mono ${drillable ? `${drillCursorClass(drillable)} ${FOCUS}` : ""}`}
                    style={{
                      backgroundColor: CELL_COLORS[tier].bg,
                      color: CELL_COLORS[tier].fg,
                      padding: "2px 6px",
                      borderRadius: 6,
                    }}
                    {...(drillable ? drillProps(row, subject) : {})}
                  >
                    {subject.available ? row.render(subject, subjects) : <span>—</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-3 py-4 text-center text-[11px] text-[#3B2D5E]">No business selected.</p>
        )}
      </div>

      {/* Desktop: the full matrix. */}
      <div className="hidden overflow-x-auto md:block">
        <table
          className="w-full table-fixed border-collapse text-left"
          style={{ minWidth: 168 + subjects.length * 148 }}
        >
          <colgroup>
            <col style={{ width: 168 }} />
            {subjects.map((subject) => (
              <col key={subject.key} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-10 min-w-[132px] border-b border-r border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]"
              >
                Business
              </th>
              {subjects.map((subject) => {
                const isMain = subject.key === mainKey;
                return (
                  <th
                    key={subject.key}
                    scope="col"
                    className={`min-w-[124px] border-b border-r border-[var(--ui-line)] px-3 py-2 align-bottom last:border-r-0 ${
                      isMain ? "bg-[#F3EEFB]" : "bg-[#FAFAFB]"
                    }`}
                  >
                    <span
                      className="block truncate text-[12px] font-bold text-[#14101F]"
                      title={subject.name || undefined}
                    >
                      {subject.name || (subject.kind === "own" ? c.yourLocation : c.savedBusiness)}
                    </span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] font-normal text-[#3B2D5E]">
                      <span className="truncate">
                        {subject.available
                          ? subject.kind === "saved"
                            ? c.googleListing
                            : c.yourLocation
                          : subject.reason}
                      </span>
                      {subject.kind === "own" ? (
                        <VerificationBadge
                          status={subject.verified ? "verified" : "unstarted"}
                          compact
                        />
                      ) : null}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              // Gap chips are computed against the main (own) column; rows
              // without the higherIsBetter flag never show one.
              const mainSubject = mainKey != null ? subjects.find((s) => s.key === mainKey) : undefined;
              const mainValue = mainSubject && mainSubject.available && row.value ? row.value(mainSubject) : null;
              return (
                <tr key={row.key} className="align-top">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 border-b border-r border-[var(--ui-line)] bg-white px-3 py-2 text-[11px] font-semibold text-[#14101F]"
                  >
                    {row.label}
                  </th>
                  {subjects.map((subject) => {
                    const value = subject.available && row.value ? row.value(subject) : null;
                    const tier = cellTier(row, subjects, subject, value);
                    const chip =
                      row.higherIsBetter === true && subject.key !== mainKey
                        ? gapChip(value, mainValue, row.higherIsBetter, row.gapUnit ?? "count")
                        : null;
                    const drillable = tier === "worst" && subject.available && onDrillDown != null;
                    const content = (
                      <>
                        {subject.available ? (
                          row.render(subject, subjects)
                        ) : (
                          <span>—</span>
                        )}
                        {chip ? (
                          <span className={`mt-1 block w-fit rounded-full px-1.5 py-0.5 text-[10px] font-bold ${chip.className}`}>
                            {chip.text}
                          </span>
                        ) : null}
                      </>
                    );
                    return (
                      <td
                        key={subject.key}
                        className="border-b border-r border-[var(--ui-line)] px-3 py-2 text-[12px] font-mono last:border-r-0"
                        style={{
                          backgroundColor: CELL_COLORS[tier].bg,
                          color: CELL_COLORS[tier].fg,
                        }}
                      >
                        {drillable ? (
                          // The interactive element nests INSIDE the cell: a
                          // role/button on the td itself would pull the cell
                          // out of the SR table walk.
                          <button
                            type="button"
                            className={`h-full w-full text-left ${drillCursorClass(drillable)} ${FOCUS}`}
                            {...drillProps(row, subject)}
                          >
                            {content}
                          </button>
                        ) : (
                          content
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatWhen(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The stored history behind the period table. Kept separate on purpose: the
 * period table answers "what changed", this one answers "what was recorded",
 * date by date, newest first.
 */
function HistoryTable({
  series,
  days,
  loading,
  error,
}: {
  series: { key: string; name: string | null; points: { at: string | null; rating: number | null; reviews: number | null }[] }[];
  days: number;
  loading: boolean;
  error: boolean;
}) {
  const { t } = useI18n();
  const c = t.benchmark.compare;
  const rows = series
    .flatMap((subject) =>
      subject.points.map((point) => ({ ...point, subject }))
    )
    .sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));

  return (
    <section className="mt-4 overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white">
      <div className="border-b border-[var(--ui-line)] px-3 py-2">
        <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
          {c.historyTitle(days)}
        </h2>
        <p className="mt-0.5 text-[10px] text-[#3B2D5E]">
          {c.historyDesc}
        </p>
      </div>

      {loading ? (
        <p className="px-3 py-4 text-[12px] text-[#3B2D5E]">{c.loadingHistory}</p>
      ) : error ? (
        <p className="px-3 py-4 text-[12px] text-[#8E1230]">{c.couldNotLoadHistory}</p>
      ) : rows.length === 0 ? (
        <p className="px-3 py-4 text-[12px] text-[#3B2D5E]">
          {c.noDataPeriod}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr>
                {[c.business, c.date, c.rating, c.reviews].map((label) => (
                  <th
                    key={label}
                    scope="col"
                    className="border-b border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]"
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.subject.key}-${row.at ?? "unknown"}`}>
                  <th
                    scope="row"
                    className="border-b border-[var(--ui-line)] px-3 py-2 text-[11px] font-semibold text-[#14101F]"
                  >
                    {row.subject.name || c.savedBusiness}
                  </th>
                  <td className="border-b border-[var(--ui-line)] px-3 py-2 font-mono text-[11px] text-[#3B2D5E]">
                    {formatWhen(row.at)}
                  </td>
                  <td className="border-b border-[var(--ui-line)] px-3 py-2 font-mono text-[11px] text-[#3B2D5E]">
                    {row.rating == null ? "—" : `${row.rating} ★`}
                  </td>
                  <td className="border-b border-[var(--ui-line)] px-3 py-2 font-mono text-[11px] text-[#3B2D5E]">
                    {row.reviews == null ? "—" : row.reviews}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Sentiment categories of the reviews table: one row per category. */
type SentimentCategory = "natural" | "positive" | "negative" | "complaining";

const SENTIMENT_CATEGORIES: SentimentCategory[] = [
  "natural",
  "positive",
  "negative",
  "complaining",
];

function getSentimentCategoryLabels(c: Record<string, any>): Record<SentimentCategory, string> {
  return { natural: c.natural, positive: c.positive, negative: c.negative, complaining: c.complaining };
}

const SENTIMENT_CATEGORY_COLORS: Record<SentimentCategory, string> = {
  natural: "#14101F",
  positive: "#B0338A",
  negative: "#FF4F6E",
  complaining: "#FF4F6E",
};

/**
 * Reviews that belong to a category row. "Complaining" means the review
 * carries complaint themes (our own locations carry the review-engine's
 * problems); "Negative" is the rest of the negatives. "Natural" is the
 * neutral bucket.
 */
function categoryReviews(
  subject: SubjectReviews,
  category: SentimentCategory
): SubjectReviews["reviews"] {
  return subject.reviews.filter((review) => {
    const problems = review.problems ?? [];
    switch (category) {
      case "natural":
        return review.sentiment === "neutral";
      case "positive":
        return review.sentiment === "positive";
      case "complaining":
        return problems.length > 0;
      case "negative":
        return review.sentiment === "negative" && problems.length === 0;
    }
  });
}

/** Cap a review's text so a line stays readable in a table cell. */
function sentimentCellText(text: string, maxLength = 140): string {
  return text.length > maxLength ? text.slice(0, maxLength) + "…" : text;
}

type PopupFilter = "newest" | "oldest" | "5" | "4" | "all";

/** All reviews of one category, in the order the popup lists them. */
function popupReviews(
  subject: SubjectReviews,
  category: SentimentCategory,
  filter: PopupFilter
): SubjectReviews["reviews"] {
  const sorted =
    filter === "oldest"
      ? [...categoryReviews(subject, category)].reverse()
      : categoryReviews(subject, category);
  if (filter === "5") return sorted.filter((review) => review.rating === 5);
  if (filter === "4") return sorted.filter((review) => review.rating === 4);
  return sorted;
}

/** Google's G, rendered as-is — the one brand mark allowed in the UI. */
function GoogleMark({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" className="shrink-0">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

/** Reviewer avatar: Google's profile photo, falling back to initials. */
function ReviewAvatar({
  name,
  photo,
  size,
}: {
  name: string | null | undefined;
  photo: string | null | undefined;
  size: "sm" | "md";
}) {
  const [failed, setFailed] = useState(false);
  const initials =
    (name || "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?";
  const box = size === "md" ? "h-7 w-7 text-[10px]" : "h-5 w-5 text-[9px]";
  if (photo && !failed) {
    return (
      <img
        src={photo}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className={`shrink-0 rounded-full border border-[#EFEDF2] object-cover ${box}`}
      />
    );
  }
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full bg-[#F4F2F7] font-bold text-[#3D1D6E] ${box}`}
    >
      {initials}
    </span>
  );
}

/**
 * One cell of the reviews table: the first three reviews of the category.
 * The middle one is fully legible; the first and third are faded. No border —
 * the reviews sit as an open list with breathing room, and the whole cell is
 * the trigger for the popup.
 */
function ResponseBadge({ answered }: { answered: boolean }) {
  const { t } = useI18n();
  const c = t.benchmark.compare;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[8px] font-bold ${
        answered
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
          : "bg-[#F4F2F7] text-[#6F6685] dark:bg-white/10 dark:text-fog/60"
      }`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${answered ? "bg-emerald-500" : "bg-[#9C94AE]"}`}
      />
      {answered ? c.answered : c.notAnswered}
    </span>
  );
}

function FadedCell({
  subject,
  category,
  color,
  onOpen,
}: {
  subject: SubjectReviews;
  category: SentimentCategory;
  color: string;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const c = t.benchmark.compare;
  const items = categoryReviews(subject, category);
  if (!items.length) {
    if (subject.reviews.length === 0) {
      return (
        <span className="text-[10px] font-semibold text-[#8A8496]">
          {subject.key.startsWith("own:") ? c.noReviewsYet : c.noRecentReviews}
        </span>
      );
    }
    return <span className="text-[#8A8496]">—</span>;
  }
  const shown = items.slice(0, 3);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      className={`h-[132px] cursor-pointer overflow-hidden rounded-[8px] px-1.5 py-1.5 transition-colors hover:bg-[#F4F2F7] ${FOCUS}`}
    >
      <ul className="flex flex-col gap-1.5">
        {shown.map((review, index) => {
          const faded =
            (index === 0 && shown.length > 1) ||
            (index === shown.length - 1 && shown.length > 2);
          return (
            <li
              key={`${review.time}-${index}`}
              className={`rounded-[8px] border border-[#EFEDF2] bg-white px-2 py-1 ${
                faded ? "opacity-45" : ""
              }`}
            >
              <div className="flex items-center gap-1.5 text-[10px]">
                <ReviewAvatar name={review.author} photo={review.author_photo} size="sm" />
                <span className="max-w-[62px] shrink-0 truncate font-semibold text-[#14101F]">
                  {review.author || c.reviewer}
                </span>
                <span className="shrink-0 font-semibold" style={{ color }}>
                  {review.rating != null ? `${review.rating}★` : "—"}
                </span>
                <span className="min-w-0 flex-1 truncate text-[#3B2D5E]">
                  {sentimentCellText(review.text, 70)}
                </span>
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-1">
                <span className="font-mono text-[9px] text-[#8A8496]">
                  {formatWhen(review.time)}
                </span>
                <ResponseBadge answered={review.answered} />
                <span className="min-w-0 truncate text-[9px] font-semibold text-[#14101F]">
                  {subject.name}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The full review list behind a cell, in a big centered modal. Cards carry
 * the Google mark, the business mark, the rating, time and the verbatim text;
 * the list scrolls. The backdrop is dimmed but inert — only the Close button
 * closes this window (no outside click, no Escape).
 */
function ReviewsPopup({
  subject,
  category,
  close,
}: {
  subject: SubjectReviews;
  category: SentimentCategory;
  close: () => void;
}) {
  const { t } = useI18n();
  const c = t.benchmark.compare;
  const labels = getSentimentCategoryLabels(c);
  const [filter, setFilter] = useState<PopupFilter>("newest");
  const rows = popupReviews(subject, category, filter);
  const color = SENTIMENT_CATEGORY_COLORS[category];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4">
      <div className="flex max-h-[86vh] w-full max-w-[860px] flex-col overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white shadow-[0_24px_80px_rgba(20,16,31,0.35)]">
        <div className="flex items-start justify-between gap-3 border-b border-[var(--ui-line)] bg-[#FAFAFB] px-4 py-3">
          <div className="flex items-center gap-2.5">
            <GoogleMark size={22} />
            <div>
              <div className="flex items-center gap-1.5">
                <GoogleMark size={13} />
                <span className="text-[10px] font-semibold uppercase tracking-wide text-[#3B2D5E]">
                  {c.googleReviews}
                </span>
              </div>
              <h2 className="text-[14px] font-bold text-[#14101F]">
                {subject.name || "—"}
              </h2>
              <p className="text-[10px] text-[#8A8496]">
                {labels[category]} · {rows.length} {c.reviews.toLowerCase()}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value as PopupFilter)}
              className="rounded-[8px] border border-[var(--ui-line)] bg-white px-2 py-1.5 text-[11px] font-semibold text-[#3B2D5E]"
            >
              <option value="newest">{c.newest}</option>
              <option value="oldest">{c.oldest}</option>
              <option value="5">5★</option>
              <option value="4">4★</option>
              <option value="all">{c.all}</option>
            </select>
            <button
              type="button"
              onClick={close}
              className={`rounded-[8px] border border-[#3D1D6E]/30 bg-white px-3 py-1.5 text-[11px] font-semibold text-[#3D1D6E] ${FOCUS}`}
            >
              {c.close}
            </button>
          </div>
        </div>

        <div className="scroll-smooth max-h-[540px] flex-1 overflow-y-auto bg-[#FAFAFB] px-4 py-4">
          {rows.length === 0 ? (
            <p className="py-10 text-center text-[12px] text-[#8A8496]">
              {c.noReviewsInCategory}
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {rows.map((review, index) => (
                <article
                  key={`${review.time}-${index}`}
                  className="rounded-[8px] border border-[#EFEDF2] bg-white p-4 shadow-[0_2px_8px_rgba(20,16,31,0.06)]"
                >
                  <div className="flex items-start gap-2">
                    <ReviewAvatar name={review.author} photo={review.author_photo} size="md" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[11px] font-bold text-[#14101F]">
                          {review.author || c.reviewer}
                        </span>
                        <GoogleMark size={11} />
                        <span className="text-[10px] text-[#8A8496]">Google</span>
                      </div>
                      <p className="mt-1 text-[13px] leading-relaxed text-[#14101F]">
                        {review.text}
                      </p>
                    </div>
                    <span
                      className="shrink-0 rounded-[8px] px-2 py-1 text-[12px] font-bold"
                      style={{ backgroundColor: `${color}1A`, color }}
                    >
                      {review.rating != null ? `${review.rating}★` : "—"}
                    </span>
                  </div>
                  <div className="mt-3 flex items-center justify-between border-t border-[#EFEDF2] pt-2">
                    <span className="font-mono text-[10px] text-[#8A8496]">
                      {formatWhen(review.time)}
                    </span>
                    <ResponseBadge answered={review.answered} />
                    <span className="text-[10px] font-semibold text-[#3B2D5E]">
                      {subject.name}
                    </span>
                  </div>
                  {review.owner_answer ? (
                    <div className="mt-3 rounded-[8px] bg-[#F4F2F7] px-3 py-2">
                      <p className="text-[9px] font-bold uppercase tracking-wide text-[#6F6685]">
                        {t.benchmark.compare.ownerReply}
                      </p>
                      <p className="mt-1 text-[11px] leading-relaxed text-[#3B2D5E]">
                        {review.owner_answer}
                      </p>
                      {review.owner_answer_time ? (
                        <p className="mt-1 font-mono text-[9px] text-[#8A8496]">
                          {formatWhen(review.owner_answer_time)}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                  {review.problems && review.problems.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {review.problems.map((problem, position) => (
                        <span
                          key={position}
                          className="rounded-[8px] bg-[#F4F2F7] px-1.5 py-0.5 text-[10px] text-[#3B2D5E]"
                        >
                          {problem}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--ui-line)] bg-white px-4 py-2">
          <span className="text-[10px] text-[#8A8496]">
            {c.reviewsNewestFirst}
          </span>
          <button
            type="button"
            onClick={close}
            className={`rounded-[8px] border border-[#3D1D6E]/30 bg-white px-3 py-1.5 text-[11px] font-semibold text-[#3D1D6E] ${FOCUS}`}
          >
            {c.close}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Sentiment-grouped reviews table, same design as the data tables above:
 * sticky label column, business columns, small radii, no gradients.
 *
 * Rows are Natural / Positive / Negative / Complaining; each business column
 * cell shows the first three reviews of that category — the middle one fully,
 * the first and third faded. Clicking a cell opens the popup with the full
 * list, filterable by recency and rating.
 */
function SentimentReviewsTable({
  subjects,
  loading,
  error,
  onRetry,
  openPopup,
}: {
  subjects: SubjectReviews[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  openPopup: (subject: SubjectReviews, category: SentimentCategory) => void;
}) {
  const { t } = useI18n();
  const c = t.benchmark.compare;
  // On small screens the business columns become one dropdown: only the
  // selected business's category rows are shown, like the other tables.
  const [mobileIndex, setMobileIndex] = useState(0);

  if (error) {
    return (
      <div role="alert" className="mt-4 rounded-[8px] border border-[#FF4F6E]/35 bg-white px-3 py-2">
        <p className="text-[12px] font-semibold text-[#B3123A]">{c.couldNotLoadReviewResponses}</p>
        <button
          type="button"
          onClick={onRetry}
          className={`mt-2 inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
        >
          {t.common.retry}
        </button>
      </div>
    );
  }

  if (loading) {
    return <p className="mt-4 text-[12px] text-[#3B2D5E]">{t.common.loading}</p>;
  }
  if (!subjects.length) {
    return (
      <p className="mt-4 text-[12px] text-[#3B2D5E]">
        {c.noDataAvailable}
      </p>
    );
  }

  return (
    <section className="mt-4 overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white">
      <div className="flex items-center justify-between border-b border-[var(--ui-line)] px-3 py-2">
        <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
          {c.reviews}
        </h2>
        <label className="flex items-center gap-2 md:hidden">
          <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
            {c.business}
          </span>
          <select
            value={mobileIndex}
            onChange={(event) => setMobileIndex(Number(event.target.value))}
            className="rounded-[8px] border border-[var(--ui-line)] bg-white px-2 py-1.5 text-[11px] font-semibold text-[#14101F]"
          >
            {subjects.map((subject, index) => (
              <option key={subject.key} value={index}>
                {subject.name || "—"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Mobile: one business's category rows. */}
      <div className="md:hidden">
        {subjects[mobileIndex] ? (
          <table className="w-full border-collapse text-left">
            <tbody>
              {SENTIMENT_CATEGORIES.map((category) => {
                const subject = subjects[mobileIndex];
                return (
                  <tr key={category}>
                    <th
                      scope="row"
                      style={{ color: SENTIMENT_CATEGORY_COLORS[category] }}
                      className="w-[92px] border-b border-r border-[var(--ui-line)] bg-white px-3 py-2 text-[11px] font-semibold"
                    >
                      {getSentimentCategoryLabels(c)[category]}
                    </th>
                    <td className="border-b border-[var(--ui-line)] px-3 py-2 align-top">
                      <FadedCell
                        subject={subject}
                        category={category}
                        color={SENTIMENT_CATEGORY_COLORS[category]}
                        onOpen={() => openPopup(subject, category)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="px-3 py-4 text-center text-[11px] text-[#3B2D5E]">
            No business selected.
          </p>
        )}
      </div>

      {/* Desktop: the full matrix. */}
      <div className="hidden overflow-x-auto md:block">
        <table
          className="w-full table-fixed border-collapse text-left"
          style={{ minWidth: 168 + subjects.length * 200 }}
        >
          <colgroup>
            <col style={{ width: 168 }} />
            {subjects.map((subject) => (
              <col key={subject.key} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-10 min-w-[132px] border-b border-r border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]"
              >
                Category
              </th>
              {subjects.map((subject) => (
                <th
                  key={subject.key}
                  scope="col"
                  className="min-w-[180px] border-b border-r border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]"
                >
                  {subject.name || "—"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SENTIMENT_CATEGORIES.map((category) => (
              <tr key={category}>
                <th
                  scope="row"
                  style={{ color: SENTIMENT_CATEGORY_COLORS[category] }}
                  className="sticky left-0 z-10 border-b border-r border-[var(--ui-line)] bg-white px-3 py-2 text-[11px] font-semibold"
                >
                  {getSentimentCategoryLabels(c)[category]}
                </th>
                {subjects.map((subject) => (
                  <td
                    key={subject.key}
                    className="border-b border-r border-[var(--ui-line)] px-3 py-2 align-top last:border-r-0"
                  >
                    <FadedCell
                      subject={subject}
                      category={category}
                      color={SENTIMENT_CATEGORY_COLORS[category]}
                      onOpen={() => openPopup(subject, category)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {subjects.some((subject) => subject.reviews.length === 0) && (
        <p className="border-t border-[var(--ui-line)] px-3 py-2 text-[11px] leading-relaxed text-[#3B2D5E]">
          {c.reviewsEmptyNote}
        </p>
      )}
    </section>
  );
}

/** Reads the current selection from the URL, tolerating older link shapes. */
function readSelection(params: URLSearchParams): CompareSelection {  const main = params.get("main");
  const vs = params.getAll("vs");
  if (main || vs.length) {
    return { main: main || null, competitors: vs.slice(0, MAX_COMPETITORS) };
  }
  const legacyS = params.getAll("s");
  if (legacyS.length) {
    return { main: legacyS[0] ?? null, competitors: legacyS.slice(1, MAX_COMPETITORS + 1) };
  }
  const left = params.get("left");
  const right = params.get("right");
  return { main: left || null, competitors: right ? [right] : [] };
}

export default function ComparePage() {
  const { t } = useI18n();
  const b = t.benchmark;
  const c = t.benchmark.compare;
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();

  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const saved: SavedPlace[] = savedQuery.data ?? [];

  const channelsQuery = useQuery({
    queryKey: ["benchmark", "own-locations-list"],
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100");
      return sortCompareChannels(
        ((data.channels ?? []) as CompareChannelOption[]).filter(
          (channel) => channel.platform === "google_reviews" && channel.status === "active"
        )
      );
    },
  });
  const own = channelsQuery.data ?? [];

  const selection = readSelection(params);
  const range = normalizeCompareRange(params.get("range"));
  const days = RANGE_DAYS[range];
  const keys = [selection.main, ...selection.competitors].filter(
    (key): key is string => Boolean(key)
  );
  const reviewThemeQueryKey = queryKeys.benchmark.reviewThemes(keys);

  const compareQuery = useQuery({
    queryKey: ["benchmark", "compare", keys.join("|"), range],
    queryFn: () => fetchComparison(keys, range),
    enabled: keys.length > 0,
  });
  const subjects = compareQuery.data?.subjects ?? [];

  const historyQuery = useQuery({
    queryKey: ["benchmark", "history", keys.join("|"), days],
    queryFn: () => fetchHistory(keys, days ?? 90, 12),
    enabled: keys.length > 0 && days != null,
  });

  const reviewsQuery = useQuery({
    queryKey: ["benchmark", "reviews", keys.join("|")],
    queryFn: () => fetchReviews(keys),
    enabled: keys.length > 0,
  });
  const reviewSubjects: SubjectReviews[] = reviewsQuery.data?.subjects ?? [];
  const reviewThemesQuery = useQuery({
    queryKey: reviewThemeQueryKey,
    queryFn: ({ signal }) => fetchReviewThemes(keys, selection.main, signal),
    enabled: keys.length > 0,
    refetchInterval: (query) => {
      if (typeof document === "undefined" || document.visibilityState !== "visible") return false;
      return query.state.data?.subjects.some((subject) => subject.status === "pending")
        ? REVIEW_THEME_POLL_MS
        : false;
    },
    refetchIntervalInBackground: false,
  });
  const [reviewsPopup, setReviewsPopup] = useState<{
    subject: SubjectReviews;
    category: SentimentCategory;
  } | null>(null);

  // Subject key → stored history points, feeding the scorecard sparklines
  // and the baseline alert.
  const historyBySubject = useMemo(() => {
    const map: Record<string, HistoryPoint[]> = {};
    for (const subject of historyQuery.data?.subjects ?? []) {
      map[subject.key] = subject.points;
    }
    return map;
  }, [historyQuery.data]);

  // Cohort tags travel on the compare response's own subjects — the only
  // place the API exposes them — so the chip filter offers exactly the
  // cohorts present in the current comparison.
  const [cohortTag, setCohortTag] = useState<string | null>(null);
  const cohortTags = useMemo(
    () => [...new Set(subjects.flatMap((s) => (s.kind === "own" ? (s.tags ?? []) : [])))].sort(),
    [subjects]
  );
  // A stale chip (selection changed, tag gone) matches nothing instead of
  // silently filtering — deactivate it.
  const activeCohortTag = cohortTag != null && cohortTags.includes(cohortTag) ? cohortTag : null;
  const mainOwnSubject =
    subjects.find((s) => s.key === selection.main && s.kind === "own") ?? null;

  const ownOptions = useMemo(() => {
    if (!activeCohortTag) return own;
    const tagged = new Set(
      subjects
        .filter((s) => s.kind === "own" && (s.tags ?? []).includes(activeCohortTag))
        .map((s) => s.id)
    );
    // The active main selection must never vanish from its own dropdown: an
    // untagged location the user already picked stays listed, so the filter
    // narrows the choice without hiding what is currently selected.
    const mainOwnId = mainOwnSubject?.id ?? null;
    return own.filter((channel) => tagged.has(channel.id) || channel.id === mainOwnId);
  }, [own, activeCohortTag, subjects, mainOwnSubject]);

  /** Drill-down from a worst-tier matrix cell: that subject's negative reviews. */
  function openWorstReviews(subject: ComparisonSubject) {
    const reviews = reviewSubjects.find((r) => r.key === subject.key);
    if (!reviews) return;
    setReviewsPopup({ subject: reviews, category: "negative" });
  }

  async function retryReviewKeywords() {
    // Stop an in-flight poll from racing the retry, then let invalidation refetch
    // the active query with the newly enqueued analysis status.
    await queryClient.cancelQueries({ queryKey: reviewThemeQueryKey });
    try {
      await retryReviewThemes(keys, selection.main);
    } catch (cause) {
      console.error("Could not retry benchmark review theme analysis", cause);
    } finally {
      await queryClient.invalidateQueries({ queryKey: reviewThemeQueryKey });
    }
  }

  const rangeOptions = useMemo(() => getRangeOptions(c as any), [c]);
  const metricRows = useMemo(() => getMetricRows(c as any), [c]);
  const periodRows = useMemo(() => getPeriodRows(c as any), [c]);
  const factRows = useMemo(() => getFactRows(c as any), [c]);

  function applyUrl(next: CompareSelection, nextRange: CompareRange) {
    const query = new URLSearchParams();
    if (next.main) query.set("main", next.main);
    next.competitors.forEach((key) => query.append("vs", key));
    if (nextRange !== "live") query.set("range", nextRange);
    const suffix = query.toString();
    router.replace(`/dashboard/benchmark/compare${suffix ? `?${suffix}` : ""}`, { scroll: false });
  }

  function update(next: CompareSelection) {
    applyUrl(next, range);
  }

  const benchSet = useMemo(
    () => saved.filter((p) => p.in_bench_set).slice(0, 5),
    [saved]
  );
  // Truly bare URL only — a legacy ?s=/?left=/?right= link parses to a real
  // selection and must not be clobbered by the defaults.
  const bareUrl = !selection.main && selection.competitors.length === 0;
  const defaultsReady = (savedQuery.isSuccess || savedQuery.isError) && (channelsQuery.isSuccess || channelsQuery.isError);
  const appliedDefaults = useRef(false);
  useEffect(() => {
    if (!bareUrl || !defaultsReady || appliedDefaults.current) return;
    appliedDefaults.current = true;
    const main = defaultCompareMain(own);
    const competitors = benchSet
      .map((p) => subjectKey("saved", p.place_id))
      .filter((key) => key !== main)
      .slice(0, 5);
    if (main || competitors.length > 0) {
      update({ main, competitors });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once when data is ready
  }, [bareUrl, defaultsReady]);

  function updateRange(nextRange: CompareRange) {
    const option = rangeOptions.find((item) => item.value === nextRange);
    // Coming-soon ranges must not be selected; they stay visible as context.
    if (!option || option.status !== "ready") return;
    applyUrl(selection, nextRange);
  }

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <Link href="/dashboard/benchmark" className={`text-[12px] font-semibold text-[#3D1D6E] ${FOCUS}`}>
        ← {t.benchmark.title}
      </Link>

      {/* Half hero: the benchmarking sentence lives in the left half. */}
      <section className="mt-4 grid overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-[#F1F2F5] lg:grid-cols-2">
        <div className="px-6 py-7 sm:px-8 sm:py-9">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#B0338A]">
            {c.benchmarkCompare}
          </p>
          <h1 className="mt-2 max-w-lg text-[24px] font-bold leading-tight text-[#14101F] sm:text-[30px]">
            {c.fiveBusinessesTitle}
          </h1>
          <p className="mt-3 max-w-lg text-[13px] leading-relaxed text-[#3B2D5E]">
            {c.fiveBusinessesDesc}
          </p>
        </div>
        <div className="relative hidden min-h-[200px] items-center justify-center lg:flex">
          <div className="absolute left-[8%] top-[16%] h-16 w-24 rounded-[8px] bg-white shadow-[0_2px_8px_rgba(20,16,31,0.08)]" />
          <div className="absolute left-[38%] top-[38%] h-16 w-24 rounded-[8px] bg-[#F6DCEB]" />
          <div className="absolute right-[34%] top-[14%] h-16 w-24 rounded-[8px] bg-[#D8459F]" />
          <div className="absolute right-[8%] top-[40%] h-16 w-24 rounded-[8px] bg-[#B0338A] shadow-[0_2px_8px_rgba(20,16,31,0.12)]" />
        </div>
      </section>

      {cohortTags.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center gap-1.5 rounded-[8px] border border-[var(--ui-line)] bg-white px-3 py-2">
          <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
            {b.cohortFilterLabel}
          </span>
          {cohortTags.map((tag) => {
            const active = tag === activeCohortTag;
            return (
              <button
                key={tag}
                type="button"
                aria-pressed={active}
                onClick={() => setCohortTag(active ? null : tag)}
                className={`rounded-[8px] border px-2 py-1 text-[11px] font-semibold transition-colors ${FOCUS} ${
                  active
                    ? "border-[#3D1D6E] bg-[#3D1D6E] text-white"
                    : "border-[var(--ui-line)] bg-[#F4F2F7] text-[#3B2D5E] hover:bg-[#F1F2F5]"
                }`}
              >
                {tag}
              </button>
            );
          })}
        </div>
      ) : null}

      {(savedQuery.isError || channelsQuery.isError) ? (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 rounded-[8px] border border-[#FF4F6E]/35 bg-white px-3 py-2">
          <p className="text-[11px] font-semibold text-[#B3123A]">
            {savedQuery.isError && channelsQuery.isError
              ? c.couldNotLoadSavedBusinesses
              : savedQuery.isError
                ? c.couldNotLoadSavedBusinesses
                : c.couldNotLoadOwnLocations}
          </p>
          {savedQuery.isError ? (
            <button type="button" onClick={() => void savedQuery.refetch()} className={`inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[10px] font-bold text-[#3D1D6E] ${FOCUS}`}>
              {t.common.retry}
            </button>
          ) : null}
          {channelsQuery.isError ? (
            <button type="button" onClick={() => void channelsQuery.refetch()} className={`inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[10px] font-bold text-[#3D1D6E] ${FOCUS}`}>
              {t.common.retry}
            </button>
          ) : null}
        </div>
      ) : null}

      {channelsQuery.isSuccess && own.length > 0 && !own.some((channel) => channel.verified) ? (
        <div className="mt-4 rounded-[8px] border border-[#B0338A]/25 bg-white px-3 py-2">
          <p className="text-[11px] font-semibold text-[#3B2D5E]">
            {c.noVerifiedBranch}{" "}
            <Link href="/dashboard/verification" className={`underline ${FOCUS}`}>
              {c.verifyBranch}
            </Link>
          </p>
        </div>
      ) : null}

      <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
        <ComparePicker selection={selection} onChange={update} saved={saved} own={ownOptions} />
      </section>

      <div className="mt-4 flex items-start gap-2 rounded-[8px] border border-[#3D1D6E]/20 bg-[#F3EEFB] px-3 py-2 md:hidden">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="mt-0.5 shrink-0 text-[#3D1D6E]">
          <path d="M12 2 1 21h22L12 2zm1 14h-2v2h2v-2zm0-7h-2v5h2V9z" fill="currentColor" />
        </svg>
        <p className="text-[11px] leading-relaxed text-[#3D1D6E]">
          {c.desktopBest}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[8px] border border-[var(--ui-line)] bg-white px-3 py-2">
        <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
          {c.period}
        </span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={c.comparisonPeriod}>
          {rangeOptions.map((option) => {
            const active = option.value === range && option.status === "ready";
            const disabled = option.status !== "ready";
            return (
              <button
                key={option.value}
                type="button"
                title={option.title}
                aria-pressed={active}
                aria-disabled={disabled || undefined}
                onClick={() => !disabled && updateRange(option.value)}
                className={`rounded-[8px] border px-3 py-1.5 text-[11px] font-semibold transition-colors ${FOCUS} ${
                  active
                    ? "border-[#3D1D6E] bg-[#3D1D6E] text-white"
                    : disabled
                      ? "border-[#E3E0E9] bg-[#FAFAFB] text-[#A9A3B2] cursor-not-allowed"
                      : "border-[var(--ui-line)] bg-white text-[#3B2D5E] hover:bg-[#F4F2F7]"
                }`}
              >
                {option.label}
                {disabled ? (
                  <span className="ml-1.5 rounded-[8px] bg-[#F3F1F5] px-1.2 py-0.1 text-[8px] font-semibold uppercase tracking-wide text-[#A9A3B2]">
                    {c.comingSoon}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <p className="text-[10px] text-[#A9A3B2]">
          {c.rangeNote}
        </p>
      </div>

      {keys.length === 0 ? (
        <p className="mt-5 rounded-[8px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-9 text-center text-[12px] text-[#3B2D5E]">
          {c.pickBusinessToBuild}
        </p>
      ) : compareQuery.isPending ? (
        <div className="mt-8 flex flex-col items-center justify-center gap-3 rounded-[8px] border border-[var(--ui-line)] bg-white px-5 py-14">
          <LogoLoader size={44} label={c.loadingComparison} showText />
          <p className="text-[11px] text-[#7C7392]">{c.pullingLatest}</p>
        </div>
      ) : compareQuery.isError ? (
        <div className="mt-5 rounded-[8px] border border-[#FF4F6E]/25 bg-white px-5 py-6">
          <p role="alert" className="text-[12px] font-semibold text-[#B32442]">{c.couldNotLoadComparison}</p>
          <button
            type="button"
            onClick={() => void compareQuery.refetch()}
            className={`mt-3 rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
          >
            {t.common.retry}
          </button>
        </div>
      ) : (
        <>
          {/* Now-tier summary: baseline drift, rank, AI read, distribution,
              fix-first tickets, completeness, trends, own-branch cards. */}
          <BaselineAlert points={mainOwnSubject ? (historyBySubject[mainOwnSubject.key] ?? []) : []} />
          {compareQuery.data?.summary ? (
            <NorthStarCard
              summary={compareQuery.data.summary}
            />
          ) : null}
          <AiSummaryCard subjects={keys} />
          {compareQuery.data?.distribution ? (
            <DistributionStrip
              subjects={compareQuery.data.subjects}
              mainKey={selection.main}
            />
          ) : null}
          {compareQuery.data?.summary ? (
            <FixFirstTickets summary={compareQuery.data.summary} subjects={subjects} />
          ) : null}
          <CompletenessCard subjects={subjects} />
          <SentimentVelocityBars
            subjects={compareQuery.data?.subjects ?? []}
            mainKey={selection.main}
          />
          <TrendChart
            history={historyQuery.data?.subjects ?? []}
            title={b.trendTitle}
            mainKey={selection.main}
            loading={historyQuery.isPending}
            error={historyQuery.error}
            onRetry={() => void historyQuery.refetch()}
          />
          <OwnScorecards
            subjects={compareQuery.data?.subjects ?? []}
            historyBySubject={historyBySubject}
            mainKey={selection.main}
          />
          {days != null ? (
            <MatrixTable
              title={c.periodLastDays(days)}
              description={c.overTimeDesc}
              rows={periodRows}
              subjects={subjects}
              mainKey={selection.main}
              onDrillDown={openWorstReviews}
              drillLoading={reviewsQuery.isPending}
            />
          ) : null}
          <MatrixTable
            title={c.numbersFromGoogle}
            description={c.numbersFromGoogleDesc}
            rows={metricRows}
            subjects={subjects}
            mainKey={selection.main}
            onDrillDown={openWorstReviews}
            drillLoading={reviewsQuery.isPending}
          />
          <MatrixTable
            title={c.whatCustomersSay}
            description={c.whatCustomersSayDesc}
            rows={factRows}
            subjects={subjects}
            mainKey={selection.main}
            onDrillDown={openWorstReviews}
            drillLoading={reviewsQuery.isPending}
          />
          <ReviewResponseTable
            subjects={reviewSubjects}
            loading={reviewsQuery.isPending}
            error={reviewsQuery.error}
            onRetry={() => void reviewsQuery.refetch()}
          />
          <SentimentReviewsTable
            subjects={reviewSubjects}
            loading={reviewsQuery.isPending}
            error={reviewsQuery.error}
            onRetry={() => void reviewsQuery.refetch()}
            openPopup={(subject, category) => setReviewsPopup({ subject, category })}
          />
          <ReviewKeywords
            key={keys.join("|")}
            data={reviewThemesQuery.data}
            mainKey={selection.main}
            loading={reviewThemesQuery.isPending}
            fetching={reviewThemesQuery.isFetching}
            error={reviewThemesQuery.error}
            onRetry={() => void retryReviewKeywords()}
          />
          {reviewsPopup ? (
            <ReviewsPopup
              subject={reviewsPopup.subject}
              category={reviewsPopup.category}
              close={() => setReviewsPopup(null)}
            />
          ) : null}
          {days != null ? (
            <HistoryTable
              series={(historyQuery.data?.subjects ?? []).map((item) => ({
                key: item.key,
                name:
                  item.name ??
                  subjects.find((subject) => subject.key === item.key)?.name ??
                  null,
                points: item.points,
              }))}
              days={days}
              loading={historyQuery.isPending}
              error={historyQuery.isError}
            />
          ) : null}
        </>
      )}
    </div>
  );
}
