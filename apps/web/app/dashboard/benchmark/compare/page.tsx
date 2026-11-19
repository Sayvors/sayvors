"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import {
  fetchComparison,
  fetchHistory,
  fetchReviews,
  fetchSavedPlaces,
  RANGE_DAYS,
  type CompareRange,
  type ComparisonSubject,
  type SavedPlace,
  type SubjectReviews,
} from "@/lib/api-benchmark";
import ComparePicker, {
  MAX_COMPETITORS,
  type CompareSelection,
} from "@/components/benchmark/ComparePicker";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

interface ChannelOption {
  id: string;
  display_name: string | null;
  platform: string;
}

type MetricKey = keyof ComparisonSubject["metrics"];
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
}

const METRIC_ROWS: Row<MetricKey>[] = [
  { key: "total_reviews", label: "Reviews total", value: (s) => s.metrics.total_reviews, render: (s) => num(s.metrics.total_reviews) },
  { key: "reviews_last_day", label: "Reviews · last day", value: (s) => s.metrics.reviews_last_day, render: (s) => num(s.metrics.reviews_last_day) },
  { key: "reviews_last_week", label: "Reviews · last week", value: (s) => s.metrics.reviews_last_week, render: (s) => num(s.metrics.reviews_last_week) },
  { key: "reviews_last_month", label: "Reviews · last month", value: (s) => s.metrics.reviews_last_month, render: (s) => num(s.metrics.reviews_last_month) },
  { key: "reviews_last_year", label: "Reviews · last year", value: (s) => s.metrics.reviews_last_year, render: (s) => num(s.metrics.reviews_last_year) },
  { key: "avg_rating", label: "Average rating", value: (s) => s.metrics.avg_rating, tierValue: (s) => (s.metrics.total_ratings !== 0 ? s.metrics.avg_rating : null), render: (s) => rating(s) },
  { key: "total_ratings", label: "Ratings total", value: (s) => s.metrics.total_ratings, render: (s) => num(s.metrics.total_ratings) },
  { key: "five_star", label: "5-star ratings", value: (s) => s.metrics.five_star, render: (s) => num(s.metrics.five_star) },
  { key: "four_star", label: "4-star ratings", value: (s) => s.metrics.four_star, render: (s) => num(s.metrics.four_star) },
  { key: "one_star", label: "1-star ratings", value: (s) => s.metrics.one_star, higherIsBetter: false, render: (s) => num(s.metrics.one_star) },
  { key: "impressions", label: "Impressions · 12 mo", value: (s) => s.metrics.impressions, render: (s) => ownerOnly(s, s.metrics.impressions) },
  { key: "calls", label: "Calls · 12 mo", value: (s) => s.metrics.calls, render: (s) => ownerOnly(s, s.metrics.calls) },
];

type PeriodKey =
  | "period_reviews"
  | "period_avg_rating"
  | "rating_change"
  | "period_impressions"
  | "period_calls";

/**
 * The period table answers "what changed in this window", never re-labels a
 * lifetime number as a window number. Saved places compute it from snapshot
 * history plus today's live values; own locations from their stored reviews.
 */
const PERIOD_ROWS: Row<PeriodKey>[] = [
  { key: "period_reviews", label: "Reviews added", value: (s) => s.metrics.period_reviews, render: (s) => num(s.metrics.period_reviews) },
  {
    key: "period_avg_rating",
    label: "Average rating in period",
    value: (s) => s.metrics.period_avg_rating,
    render: (s) => (s.metrics.period_avg_rating == null ? "—" : `${s.metrics.period_avg_rating} ★`),
  },
  {
    key: "rating_change",
    label: "Rating change",
    value: (s) => s.metrics.rating_change,
    render: (s) => signed(s.metrics.rating_change),
  },
  { key: "period_impressions", label: "Impressions", render: (s) => ownerOnly(s, s.metrics.period_impressions) },
  { key: "period_calls", label: "Calls", render: (s) => ownerOnly(s, s.metrics.period_calls) },
];

type RangeStatus = "ready" | "coming_soon";

const RANGE_OPTIONS: { value: CompareRange; label: string; title: string; status: RangeStatus }[] = [
  { value: "live", label: "Live", title: "Live values from Google, right now", status: "ready" },
  { value: "30d", label: "30 days", title: "Values for the last 30 days", status: "ready" },
  { value: "90d", label: "90 days", title: "Values for the last 90 days", status: "coming_soon" },
  { value: "365d", label: "1 year", title: "Values for the last 12 months", status: "coming_soon" },
];

/** Disabled ranges fall back to Live so an old link still renders. */
function normalizeRange(value: string | null): CompareRange {
  return value === "30d" ? "30d" : "live";
}

const FACT_ROWS: Row<FactKey>[] = [  { key: "positive_pct", label: "Positive sentiment", value: (s) => s.facts.positive_pct, render: (s) => pct(s.facts.positive_pct) },
  { key: "negative_pct", label: "Negative sentiment", value: (s) => s.facts.negative_pct, higherIsBetter: false, render: (s) => pct(s.facts.negative_pct) },
  { key: "branch", label: "Branch / location", render: (s) => s.facts.branch ?? "—" },
  { key: "employee_mentions", label: "Team mentioned", value: (s) => s.facts.employee_mentions, render: (s) => num(s.facts.employee_mentions) },
  { key: "working_hard_mentions", label: "Praised for hard work", value: (s) => s.facts.working_hard_mentions, render: (s) => num(s.facts.working_hard_mentions) },
  { key: "menu_price_mentions", label: "Menu & price mentions", value: (s) => s.facts.menu_price_mentions, render: (s) => num(s.facts.menu_price_mentions) },
  { key: "parking_praised", label: "Parking · positive", value: (s) => s.facts.parking_praised, render: (s) => num(s.facts.parking_praised) },
  { key: "parking_criticised", label: "Parking · negative", value: (s) => s.facts.parking_criticised, higherIsBetter: false, render: (s) => num(s.facts.parking_criticised) },
  { key: "services", label: "Services", render: (s, all) => serviceChips(s.facts.services, all) },
  { key: "top_problems", label: "Top problems", render: (s) => chips(s.facts.top_problems) },
  { key: "named_team", label: "Named team", render: (s) => namedTeam(s.facts.named_team) },
];

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
            className="rounded-[6px] px-1.5 py-0.5 text-[10px] font-semibold"
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
  return value == null ? "—" : `${value}%`;
}

/** A rating movement: sign is the message, so keep it visible. */
function signed(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value === 0) return "0.00";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

/** A listing with no ratings has no average; 0.0 would read as a real score. */
function rating(subject: ComparisonSubject): string {
  const { avg_rating, total_ratings } = subject.metrics;
  if (avg_rating == null || total_ratings === 0) return "—";
  return `${avg_rating} ★`;
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
          className="rounded-[6px] bg-[#F4F2F7] px-1.5 py-0.5 text-[10px] font-semibold text-[#3B2D5E]"
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
 * One table per fact group, in the shape the comparison is read in:
 * `Reviews total | 300 | 500 | 500 | 500 | 500 | 500`.
 *
 * The label column is sticky so the fact name stays readable while the six
 * business columns scroll horizontally on a narrow screen.
 */
function MatrixTable<T extends string>({
  title,
  description,
  rows,
  subjects,
  mainKey,
}: {
  title: string;
  description?: string;
  rows: Row<T>[];
  subjects: ComparisonSubject[];
  mainKey: string | null;
}) {
  return (
    <section className="mt-4 overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white">
      <div className="border-b border-[var(--ui-line)] px-3 py-2">
        <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{title}</h2>
        {description ? <p className="mt-0.5 text-[10px] text-[#3B2D5E]">{description}</p> : null}
      </div>

      <div className="overflow-x-auto">
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
                      {subject.name || (subject.kind === "own" ? "Your location" : "Saved business")}
                    </span>
                    <span className="mt-0.5 block truncate text-[10px] font-normal text-[#3B2D5E]">
                      {subject.available
                        ? subject.kind === "saved"
                          ? "Google listing"
                          : "Your location"
                        : subject.reason}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
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
                    return (
                      <td
                        key={subject.key}
                        className="border-b border-r border-[var(--ui-line)] px-3 py-2 text-[12px] font-mono last:border-r-0"
                        style={{
                          backgroundColor: CELL_COLORS[tier].bg,
                          color: CELL_COLORS[tier].fg,
                        }}
                      >
                        {subject.available ? (
                          row.render(subject, subjects)
                        ) : (
                          <span>—</span>
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
  const rows = series
    .flatMap((subject) =>
      subject.points.map((point) => ({ ...point, subject }))
    )
    .sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));

  return (
    <section className="mt-4 overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white">
      <div className="border-b border-[var(--ui-line)] px-3 py-2">
        <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
          History · last {days} days
        </h2>
        <p className="mt-0.5 text-[10px] text-[#3B2D5E]">
          Rating and review count at the start and end of the selected period.
        </p>
      </div>

      {loading ? (
        <p className="px-3 py-4 text-[12px] text-[#3B2D5E]">Loading history…</p>
      ) : error ? (
        <p className="px-3 py-4 text-[12px] text-[#8E1230]">Could not load history.</p>
      ) : rows.length === 0 ? (
        <p className="px-3 py-4 text-[12px] text-[#3B2D5E]">
          No data for this period yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr>
                {["Business", "Date", "Rating", "Reviews"].map((label) => (
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
                    {row.subject.name || "Saved business"}
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

const SENTIMENT_CATEGORY_LABELS: Record<SentimentCategory, string> = {
  natural: "Natural",
  positive: "Positive",
  negative: "Negative",
  complaining: "Complaining",
};

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

/**
 * One cell of the reviews table: the first three reviews of the category.
 * The middle one is fully legible; the first and third are faded so the cell
 * reads as a preview of the longer list in the popup.
 */
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
  const items = categoryReviews(subject, category);
  if (!items.length) return <span className="text-[#8A8496]">—</span>;
  const shown = items.slice(0, 3);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      className="relative h-[72px] cursor-pointer overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white px-1.5 py-1"
    >
      <ul>
        {shown.map((review, index) => {
          const faded =
            (index === 0 && shown.length > 1) ||
            (index === shown.length - 1 && shown.length > 2);
          return (
            <li
              key={`${review.time}-${index}`}
              className={`flex items-baseline gap-1 text-[10px] leading-[22px] truncate ${
                faded ? "opacity-45" : ""
              }`}
            >
              <span className="shrink-0 font-semibold" style={{ color }}>
                {review.rating != null ? `${review.rating}★` : "—"}
              </span>
              <span className="min-w-0 flex-1 truncate text-[#3B2D5E]">
                {sentimentCellText(review.text)}
              </span>
              <span className="shrink-0 font-mono text-[9px] text-[#3B2D5E]">
                {formatWhen(review.time)}
              </span>
              <span className="shrink-0 font-semibold text-[#14101F]">
                {subject.name}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The full review list behind a cell, in a popup. Filtered by recency and
 * rating; only the Close button closes it — the card is modal on purpose.
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
  const [filter, setFilter] = useState<PopupFilter>("newest");
  const rows = popupReviews(subject, category, filter);
  const color = SENTIMENT_CATEGORY_COLORS[category];
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-3 pt-[6vh]">
      <div className="w-full max-w-[640px] overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white shadow-[0_8px_30px_rgba(20,16,31,0.14)]">
        <div className="flex items-center justify-between border-b border-[var(--ui-line)] px-3 py-2">
          <h2 className="text-[13px] font-bold text-[#14101F]">
            {subject.name || "—"} · {SENTIMENT_CATEGORY_LABELS[category]}
          </h2>
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value as PopupFilter)}
            className="rounded-[6px] border border-[var(--ui-line)] bg-white px-2 py-1 text-[11px]"
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="5">5★</option>
            <option value="4">4★</option>
            <option value="all">All</option>
          </select>
        </div>

        <div className="max-h-[60vh] space-y-2 overflow-y-auto px-3 py-3">
          {rows.length === 0 ? (
            <p className="text-center text-[12px] text-[#8A8496]">
              No reviews in this category.
            </p>
          ) : (
            rows.map((review, index) => (
              <div
                key={`${review.time}-${index}`}
                className="border-b border-[var(--ui-line)] py-2 last:border-b-0"
              >
                <div className="flex items-baseline gap-2">
                  <span className="shrink-0 font-semibold" style={{ color }}>
                    {review.rating != null ? `${review.rating}★` : "—"}
                  </span>
                  <span className="font-mono text-[10px] text-[#3B2D5E]">
                    {formatWhen(review.time)}
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] leading-snug text-[#14101F]">
                  {review.text}
                </p>
              </div>
            ))
          )}
        </div>

        <div className="flex items-center justify-end border-t border-[var(--ui-line)] px-3 py-2">
          <button
            type="button"
            onClick={close}
            className={`rounded-[8px] border border-[#3D1D6E]/30 bg-white px-3 py-1.5 text-[11px] font-semibold text-[#3D1D6E] ${FOCUS}`}
          >
            Close
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
  openPopup,
}: {
  subjects: SubjectReviews[];
  loading: boolean;
  openPopup: (subject: SubjectReviews, category: SentimentCategory) => void;
}) {
  if (loading) {
    return <p className="mt-4 text-[12px] text-[#3B2D5E]">Loading reviews…</p>;
  }
  if (!subjects.length) {
    return (
      <p className="mt-4 text-[12px] text-[#3B2D5E]">
        No reviews are stored for these businesses yet.
      </p>
    );
  }

  return (
    <section className="mt-4 overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white">
      <div className="border-b border-[var(--ui-line)] px-3 py-2">
        <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
          Reviews by category
        </h2>
      </div>

      <div className="overflow-x-auto">
        <table
          className="w-full table-fixed border-collapse text-left"
          style={{ minWidth: 168 + subjects.length * 160 }}
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
                  className="min-w-[140px] border-b border-r border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]"
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
                  {SENTIMENT_CATEGORY_LABELS[category]}
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
  const router = useRouter();
  const params = useSearchParams();

  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const saved: SavedPlace[] = savedQuery.data ?? [];

  const channelsQuery = useQuery({
    queryKey: ["benchmark", "own-locations-list"],
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100");
      return ((data.channels ?? []) as ChannelOption[]).filter(
        (channel) => channel.platform === "google_reviews"
      );
    },
  });
  const own = channelsQuery.data ?? [];

  const selection = readSelection(params);
  const range = normalizeRange(params.get("range"));
  const days = RANGE_DAYS[range];
  const keys = [selection.main, ...selection.competitors].filter(
    (key): key is string => Boolean(key)
  );

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
  const [reviewsPopup, setReviewsPopup] = useState<{
    subject: SubjectReviews;
    category: SentimentCategory;
  } | null>(null);

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

  function updateRange(nextRange: CompareRange) {
    const option = RANGE_OPTIONS.find((item) => item.value === nextRange);
    // Coming-soon ranges must not be selected; they stay visible as context.
    if (!option || option.status !== "ready") return;
    applyUrl(selection, nextRange);
  }

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <Link href="/dashboard/benchmark" className={`text-[12px] font-semibold text-[#3D1D6E] ${FOCUS}`}>
        ← Back to benchmark
      </Link>

      {/* Half hero: the benchmarking sentence lives in the left half. */}
      <section className="mt-4 grid overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-[#F1F2F5] lg:grid-cols-2">
        <div className="px-6 py-7 sm:px-8 sm:py-9">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#B0338A]">
            Benchmark / Compare
          </p>
          <h1 className="mt-2 max-w-lg text-[24px] font-bold leading-tight text-[#14101F] sm:text-[30px]">
            Five businesses against yours.
          </h1>
          <p className="mt-3 max-w-lg text-[13px] leading-relaxed text-[#3B2D5E]">
            Pick one business on the left and up to five on the right. Every row is
            one fact, every column one business — the leader in each row is marked,
            and anything Google does not publish stays blank instead of becoming a
            zero.
          </p>
        </div>
        <div className="relative hidden min-h-[200px] items-center justify-center lg:flex">
          <div className="absolute left-[8%] top-[16%] h-16 w-24 rounded-[10px] bg-white shadow-[0_2px_8px_rgba(20,16,31,0.08)]" />
          <div className="absolute left-[38%] top-[38%] h-16 w-24 rounded-[10px] bg-[#F6DCEB]" />
          <div className="absolute right-[34%] top-[14%] h-16 w-24 rounded-[10px] bg-[#D8459F]" />
          <div className="absolute right-[8%] top-[40%] h-16 w-24 rounded-[10px] bg-[#B0338A] shadow-[0_2px_8px_rgba(20,16,31,0.12)]" />
        </div>
      </section>

      <section className="mt-4 rounded-[12px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
        <ComparePicker selection={selection} onChange={update} saved={saved} own={own} />
      </section>

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[12px] border border-[var(--ui-line)] bg-white px-3 py-2">
        <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
          Period
        </span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Comparison period">
          {RANGE_OPTIONS.map((option) => {
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
                  <span className="ml-1.5 rounded-[4px] bg-[#F3F1F5] px-1.2 py-0.1 text-[8px] font-semibold uppercase tracking-wide text-[#A9A3B2]">
                    coming soon
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <p className="text-[10px] text-[#A9A3B2]">
          Live and 30 days are active. 90 days and 1 year unlock as the scraper fills history.
        </p>
      </div>

      {keys.length === 0 ? (
        <p className="mt-5 rounded-[12px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-9 text-center text-[12px] text-[#3B2D5E]">
          Pick a business in either dropdown to build the table.
        </p>
      ) : compareQuery.isPending ? (
        <p className="mt-5 text-[12px] text-[#3B2D5E]">Loading comparison…</p>
      ) : compareQuery.isError ? (
        <p className="mt-5 text-[12px] text-red-700">Could not load the comparison.</p>
      ) : (
        <>
          {days != null ? (
            <MatrixTable
              title={`Period · last ${days} days`}
              description="Reviews added, rating movement, views and calls for the selected period. Blank means the data is not available, never a zero."
              rows={PERIOD_ROWS}
              subjects={subjects}
              mainKey={selection.main}
            />
          ) : null}
          <MatrixTable
            title="Numbers from Google"
            description="Reviews, ratings and listing performance. Views and calls are only released to the listing's owner, so a competitor's column stays blank there."
            rows={METRIC_ROWS}
            subjects={subjects}
            mainKey={selection.main}
          />
          <MatrixTable
            title="What customers say"
            description="Scanned from the most recent reviews; owner-only facts stay blank for competitors."
            rows={FACT_ROWS}
            subjects={subjects}
            mainKey={selection.main}
          />
          <SentimentReviewsTable
            subjects={reviewSubjects}
            loading={reviewsQuery.isPending}
            openPopup={(subject, category) => setReviewsPopup({ subject, category })}
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
