"use client";

import { Fragment, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import {
  fetchComparison,
  fetchSavedPlaces,
  type ComparisonSubject,
  type SavedPlace,
} from "@/lib/api-benchmark";
import VerificationBadge from "@/components/shared/VerificationBadge";
import ComparePicker from "@/components/benchmark/ComparePicker";

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
  value?: (subject: ComparisonSubject) => number | null;
  higherIsBetter?: boolean;
}

const METRIC_ROWS: Row<MetricKey>[] = [
  { key: "total_reviews", label: "Total reviews", value: (s) => s.metrics.total_reviews, render: (s) => num(s.metrics.total_reviews) },
  { key: "reviews_last_day", label: "Reviews · last day", value: (s) => s.metrics.reviews_last_day, render: (s) => num(s.metrics.reviews_last_day) },
  { key: "reviews_last_week", label: "Reviews · last week", value: (s) => s.metrics.reviews_last_week, render: (s) => num(s.metrics.reviews_last_week) },
  { key: "reviews_last_month", label: "Reviews · last month", value: (s) => s.metrics.reviews_last_month, render: (s) => num(s.metrics.reviews_last_month) },
  { key: "reviews_last_year", label: "Reviews · last year", value: (s) => s.metrics.reviews_last_year, render: (s) => num(s.metrics.reviews_last_year) },
  { key: "avg_rating", label: "Average rating", value: (s) => s.metrics.avg_rating, render: (s) => num(s.metrics.avg_rating, "★") },
  { key: "total_ratings", label: "Total ratings", value: (s) => s.metrics.total_ratings, render: (s) => num(s.metrics.total_ratings) },
  { key: "five_star", label: "5-star ratings", value: (s) => s.metrics.five_star, render: (s) => num(s.metrics.five_star) },
  { key: "four_star", label: "4-star ratings", value: (s) => s.metrics.four_star, render: (s) => num(s.metrics.four_star) },
  { key: "one_star", label: "1-star ratings", value: (s) => s.metrics.one_star, higherIsBetter: false, render: (s) => num(s.metrics.one_star) },
  { key: "impressions", label: "Impressions (12 mo)", value: (s) => s.metrics.impressions, render: (s) => ownerOnly(s, s.metrics.impressions) },
  { key: "calls", label: "Calls (12 mo)", value: (s) => s.metrics.calls, render: (s) => ownerOnly(s, s.metrics.calls) },
];

const FACT_ROWS: Row<FactKey>[] = [
  { key: "positive_pct", label: "Positive sentiment", value: (s) => s.facts.positive_pct, render: (s) => pct(s.facts.positive_pct) },
  { key: "negative_pct", label: "Negative sentiment", value: (s) => s.facts.negative_pct, higherIsBetter: false, render: (s) => pct(s.facts.negative_pct) },
  { key: "branch", label: "Branch / location", render: (s) => s.facts.branch ?? "—" },
  { key: "employee_mentions", label: "Team mentioned in reviews", value: (s) => s.facts.employee_mentions, render: (s) => num(s.facts.employee_mentions) },
  { key: "working_hard_mentions", label: "Praised for working hard", value: (s) => s.facts.working_hard_mentions, render: (s) => num(s.facts.working_hard_mentions) },
  { key: "menu_price_mentions", label: "Menu & price mentions", value: (s) => s.facts.menu_price_mentions, render: (s) => num(s.facts.menu_price_mentions) },
  { key: "parking_praised", label: "Parking · positive mentions", value: (s) => s.facts.parking_praised, render: (s) => num(s.facts.parking_praised) },
  { key: "parking_criticised", label: "Parking · negative mentions", value: (s) => s.facts.parking_criticised, higherIsBetter: false, render: (s) => num(s.facts.parking_criticised) },
  { key: "services", label: "Services", render: (s) => chips(s.facts.services) },
  { key: "top_problems", label: "Top problems", render: (s) => chips(s.facts.top_problems) },
  { key: "named_team", label: "Named team members", render: (s) => namedTeam(s.facts.named_team) },
];

const NOTE_ROWS: Row<"notes">[] = [
  {
    key: "notes",
    label: "Where these numbers come from",
    render: (s) => (
      <ul className="list-disc pl-4 text-[10px] leading-relaxed text-[#3B2D5E]">
        {s.notes.map((note) => <li key={note}>{note}</li>)}
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

function ownerOnly(subject: ComparisonSubject, value: number | null): ReactNode {
  if (subject.kind === "saved") {
    return <span className="text-[10px] text-[#8A8496]">Owner only</span>;
  }
  return num(value);
}

function chips(items: string[] | undefined): ReactNode {
  if (!items?.length) return <span className="text-[#8A8496]">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((item) => (
        <span key={item} className="rounded-[8px] bg-[#F4F2F7] px-2 py-0.5 text-[10px] font-semibold text-[#3B2D5E]">
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
        <span key={member.name} className="text-[11px]">
          <strong className="font-bold">{member.name}</strong>
          <span className="text-[#3B2D5E]"> · {member.mentions} mentions</span>
        </span>
      ))}
    </span>
  );
}

function MatrixTable<T extends string>({
  title,
  description,
  rows,
  subjects,
}: {
  title: string;
  description?: string;
  rows: Row<T>[];
  subjects: ComparisonSubject[];
}) {
  return (
    <section className="mt-5 overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white">
      <div className="border-b border-[var(--ui-line)] bg-[#F4F2F7] px-4 py-3">
        <h2 className="text-[14px] font-bold text-[#14101F]">{title}</h2>
        {description ? <p className="mt-0.5 text-[10px] text-[#3B2D5E]">{description}</p> : null}
      </div>
      <div className="overflow-x-auto">
        <div
          className="grid"
          style={{
            gridTemplateColumns: `minmax(160px, 200px) repeat(${subjects.length}, minmax(160px, 1fr))`,
            minWidth: `${200 + subjects.length * 170}px`,
          }}
        >
          <div className="border-b border-r border-[var(--ui-line)] bg-white px-4 py-3 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
            Metric
          </div>
          {subjects.map((subject) => (
            <div key={subject.key} className="min-w-0 border-b border-r border-[var(--ui-line)] px-4 py-3 last:border-r-0">
              <div className="flex min-w-0 items-center gap-2">
                <h3 className="truncate text-[13px] font-bold text-[#14101F]" title={subject.name || subject.id}>
                  {subject.name || subject.id}
                </h3>
                {subject.available ? (
                  <VerificationBadge status={subject.verified ? "verified" : "unstarted"} compact />
                ) : null}
              </div>
              <p className="mt-0.5 truncate text-[10px] text-[#3B2D5E]">
                {subject.available
                  ? subject.kind === "saved" ? "Google Places listing" : "Your connected location"
                  : subject.reason}
              </p>
            </div>
          ))}

          {rows.map((row) => {
            const values = subjects
              .filter((subject) => subject.available && row.value)
              .map((subject) => row.value!(subject))
              .filter((value): value is number => value != null);
            const best = values.length > 1
              ? (row.higherIsBetter === false ? Math.min(...values) : Math.max(...values))
              : null;
            return (
              <Fragment key={row.key}>
                <div className="border-b border-r border-[var(--ui-line)] px-4 py-2.5 text-[11px] font-semibold text-[#14101F]">
                  {row.label}
                </div>
                {subjects.map((subject) => {
                  const value = subject.available && row.value ? row.value(subject) : null;
                  const winning = best != null && value === best;
                  return (
                    <div
                      key={subject.key}
                      className={`border-b border-r px-4 py-2.5 text-[12px] last:border-r-0 ${
                        winning ? "font-bold text-[#B0338A]" : "font-mono text-[#3B2D5E]"
                      } border-[var(--ui-line)]`}
                    >
                      {subject.available
                        ? row.render(subject)
                        : <span className="text-[10px] text-[#8E1230]">{subject.reason}</span>}
                    </div>
                  );
                })}
              </Fragment>
            );
          })}
        </div>
      </div>
    </section>
  );
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

  // Card links use ?left=/?right=; the picker uses repeated ?s= params.
  const selected = params.getAll("s");
  const selectedKeys = selected.length
    ? selected
    : [params.get("left"), params.get("right")].filter((value): value is string => Boolean(value));

  const compareQuery = useQuery({
    queryKey: ["benchmark", "compare", selectedKeys.join("|")],
    queryFn: () => fetchComparison(selectedKeys),
    enabled: selectedKeys.length > 0,
  });
  const subjects = compareQuery.data?.subjects ?? [];

  function update(keys: string[]) {
    const next = new URLSearchParams();
    keys.forEach((key) => next.append("s", key));
    const query = next.toString();
    router.replace(`/dashboard/benchmark/compare${query ? `?${query}` : ""}`, { scroll: false });
  }

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <Link href="/dashboard/benchmark" className={`text-[12px] font-semibold text-[#3D1D6E] ${FOCUS}`}>
        ← Back to benchmark
      </Link>

      {/* Half hero: the benchmarking sentence lives in the left half. */}
      <section className="mt-4 grid overflow-hidden rounded-[24px] border border-[var(--ui-line)] bg-[#F1F2F5] lg:grid-cols-2">
        <div className="px-6 py-8 sm:px-8 sm:py-10">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#B0338A]">
            Benchmark / Compare
          </p>
          <h1 className="mt-2 max-w-lg text-[24px] font-bold leading-tight text-[#14101F] sm:text-[30px]">
            Every business. One honest table.
          </h1>
          <p className="mt-3 max-w-lg text-[13px] leading-relaxed text-[#3B2D5E]">
            Put up to six saved competitors and your own branches in a single
            comparison. Each column is one business, each row a fact — so you
            can see who leads on reviews, ratings and customer sentiment at a
            glance, with no invented numbers filling the gaps.
          </p>
        </div>
        <div className="relative hidden min-h-[220px] items-center justify-center lg:flex">
          <div className="absolute left-[10%] top-[14%] h-20 w-32 rounded-[16px] bg-white shadow-[0_2px_8px_rgba(20,16,31,0.08)]" />
          <div className="absolute bottom-[16%] left-[34%] h-20 w-32 rounded-[16px] bg-[#F6DCEB]" />
          <div className="absolute right-[10%] top-[18%] h-20 w-32 rounded-[16px] bg-[#D8459F]" />
          <div className="absolute bottom-[12%] right-[22%] h-20 w-32 rounded-[16px] bg-[#B0338A] shadow-[0_2px_8px_rgba(20,16,31,0.12)]" />
        </div>
      </section>

      <section className="mt-5 rounded-[16px] border border-[var(--ui-line)] bg-white p-4">
        <p className="mb-3 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
          Choose the businesses to compare
        </p>
        <ComparePicker selected={selectedKeys} onChange={update} saved={saved} own={own} />
      </section>

      {selectedKeys.length === 0 ? (
        <p className="mt-6 rounded-[16px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-10 text-center text-[12px] text-[#3B2D5E]">
          Tick at least one business above to build the comparison table.
        </p>
      ) : compareQuery.isPending ? (
        <p className="mt-6 text-[12px] text-[#3B2D5E]">Loading comparison…</p>
      ) : compareQuery.isError ? (
        <p className="mt-6 text-[12px] text-red-700">Could not load the comparison.</p>
      ) : (
        <>
          <MatrixTable
            title="Numbers from Google"
            description="Reviews, ratings and listing performance. Owner-only figures stay blank for competitors."
            rows={METRIC_ROWS}
            subjects={subjects}
          />
          <MatrixTable
            title="What customers say"
            description="Signals scanned from the most recent reviews, plus services and issues from your own locations."
            rows={FACT_ROWS}
            subjects={subjects}
          />
          <MatrixTable
            title="Sources & limits"
            rows={NOTE_ROWS}
            subjects={subjects}
          />
        </>
      )}
    </div>
  );
}
