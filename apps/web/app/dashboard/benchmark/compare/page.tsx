"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import {
  fetchComparison,
  fetchHistory,
  fetchSavedPlaces,
  RANGE_DAYS,
  type CompareRange,
  type ComparisonSubject,
  type SavedPlace,
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
  render: (subject: ComparisonSubject) => ReactNode;
  /** Present only for rows that can be won; drives the per-row highlight. */
  value?: (subject: ComparisonSubject) => number | null;
  higherIsBetter?: boolean;
}

const METRIC_ROWS: Row<MetricKey>[] = [
  { key: "total_reviews", label: "Reviews total", value: (s) => s.metrics.total_reviews, render: (s) => num(s.metrics.total_reviews) },
  { key: "reviews_last_day", label: "Reviews · last day", value: (s) => s.metrics.reviews_last_day, render: (s) => num(s.metrics.reviews_last_day) },
  { key: "reviews_last_week", label: "Reviews · last week", value: (s) => s.metrics.reviews_last_week, render: (s) => num(s.metrics.reviews_last_week) },
  { key: "reviews_last_month", label: "Reviews · last month", value: (s) => s.metrics.reviews_last_month, render: (s) => num(s.metrics.reviews_last_month) },
  { key: "reviews_last_year", label: "Reviews · last year", value: (s) => s.metrics.reviews_last_year, render: (s) => num(s.metrics.reviews_last_year) },
  { key: "avg_rating", label: "Average rating", value: (s) => s.metrics.avg_rating, render: (s) => rating(s) },
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

const RANGE_OPTIONS: { value: CompareRange; label: string; title: string }[] = [
  { value: "live", label: "Live", title: "Live values from Google, right now" },
  { value: "30d", label: "30 days", title: "Values for the last 30 days" },
  { value: "90d", label: "90 days", title: "Values for the last 90 days" },
  { value: "365d", label: "1 year", title: "Values for the last 12 months" },
];

function normalizeRange(value: string | null): CompareRange {
  return value === "30d" || value === "90d" || value === "365d" ? value : "live";
}

const FACT_ROWS: Row<FactKey>[] = [  { key: "positive_pct", label: "Positive sentiment", value: (s) => s.facts.positive_pct, render: (s) => pct(s.facts.positive_pct) },
  { key: "negative_pct", label: "Negative sentiment", value: (s) => s.facts.negative_pct, higherIsBetter: false, render: (s) => pct(s.facts.negative_pct) },
  { key: "branch", label: "Branch / location", render: (s) => s.facts.branch ?? "—" },
  { key: "employee_mentions", label: "Team mentioned", value: (s) => s.facts.employee_mentions, render: (s) => num(s.facts.employee_mentions) },
  { key: "working_hard_mentions", label: "Praised for hard work", value: (s) => s.facts.working_hard_mentions, render: (s) => num(s.facts.working_hard_mentions) },
  { key: "menu_price_mentions", label: "Menu & price mentions", value: (s) => s.facts.menu_price_mentions, render: (s) => num(s.facts.menu_price_mentions) },
  { key: "parking_praised", label: "Parking · positive", value: (s) => s.facts.parking_praised, render: (s) => num(s.facts.parking_praised) },
  { key: "parking_criticised", label: "Parking · negative", value: (s) => s.facts.parking_criticised, higherIsBetter: false, render: (s) => num(s.facts.parking_criticised) },
  { key: "services", label: "Services", render: (s) => chips(s.facts.services) },
  { key: "top_problems", label: "Top problems", render: (s) => chips(s.facts.top_problems) },
  { key: "named_team", label: "Named team", render: (s) => namedTeam(s.facts.named_team) },
];

const NOTE_ROWS: Row<"notes">[] = [
  {
    key: "notes",
    label: "Where these numbers come from",
    render: (s) => (
      <ul className="list-disc pl-3.5 text-[10px] leading-relaxed text-[#3B2D5E]">
        {s.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    ),
  },
];

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

function ownerOnly(subject: ComparisonSubject, value: number | null): ReactNode {
  // Google releases views and calls only to the listing's owner, so a
  // competitor column can never have them. A dash keeps the row aligned with
  // every other unknown fact; the section note explains why.
  if (subject.kind === "saved") {
    return <span className="text-[#8A8496]">—</span>;
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
              const values = subjects
                .filter((subject) => subject.available && row.value)
                .map((subject) => row.value!(subject))
                .filter((value): value is number => value != null);
              const best =
                values.length > 1
                  ? row.higherIsBetter === false
                    ? Math.min(...values)
                    : Math.max(...values)
                  : null;

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
                    const winning = best != null && value === best;
                    return (
                      <td
                        key={subject.key}
                        className={`border-b border-r border-[var(--ui-line)] px-3 py-2 text-[12px] last:border-r-0 ${
                          winning ? "font-bold text-[#B0338A]" : "font-mono text-[#3B2D5E]"
                        }`}
                      >
                        {subject.available ? (
                          row.render(subject)
                        ) : (
                          <span className="font-sans text-[#8A8496]">—</span>
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
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
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
            const active = option.value === range;
            return (
              <button
                key={option.value}
                type="button"
                title={option.title}
                aria-pressed={active}
                onClick={() => updateRange(option.value)}
                className={`rounded-[8px] border px-3 py-1.5 text-[11px] font-semibold transition-colors ${FOCUS} ${
                  active
                    ? "border-[#3D1D6E] bg-[#3D1D6E] text-white"
                    : "border-[var(--ui-line)] bg-white text-[#3B2D5E] hover:bg-[#F4F2F7]"
                }`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <span className="text-[10px] text-[#8A8496]">
          {range === "live" ? "Live values from Google, right now." : "Values for the selected period."}
        </span>
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
          <MatrixTable
            title="Sources & limits"
            rows={NOTE_ROWS}
            subjects={subjects}
            mainKey={selection.main}
          />
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
