"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import {
  fetchComparison,
  fetchSavedPlaces,
  subjectKey,
  type ComparisonSubject,
  type SavedPlace,
} from "@/lib/api-benchmark";
import VerificationBadge from "@/components/shared/VerificationBadge";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

interface ChannelOption {
  id: string;
  display_name: string | null;
  platform: string;
}

type MetricKey = keyof ComparisonSubject["metrics"];
type FactKey = keyof ComparisonSubject["facts"];

const METRIC_ROWS: { key: MetricKey; label: string; suffix?: string }[] = [
  { key: "total_reviews", label: "Total reviews" },
  { key: "reviews_last_day", label: "Reviews · last day" },
  { key: "reviews_last_week", label: "Reviews · last week" },
  { key: "reviews_last_month", label: "Reviews · last month" },
  { key: "reviews_last_year", label: "Reviews · last year" },
  { key: "avg_rating", label: "Average rating", suffix: "★" },
  { key: "total_ratings", label: "Total ratings" },
  { key: "five_star", label: "5-star ratings" },
  { key: "four_star", label: "4-star ratings" },
  { key: "one_star", label: "1-star ratings" },
  { key: "impressions", label: "Impressions (12 mo)" },
  { key: "calls", label: "Calls (12 mo)" },
];

const FACT_ROWS: { key: FactKey; label: string; hint?: string }[] = [
  { key: "positive_pct", label: "Positive sentiment" },
  { key: "negative_pct", label: "Negative sentiment" },
  { key: "branch", label: "Branch / location" },
  { key: "employee_mentions", label: "Team mentioned in reviews" },
  { key: "working_hard_mentions", label: "Praised for working hard" },
  { key: "menu_price_mentions", label: "Menu & price mentions" },
  { key: "parking_praised", label: "Parking · positive mentions" },
  { key: "parking_criticised", label: "Parking · negative mentions" },
  { key: "services", label: "Services" },
  { key: "top_problems", label: "Top problems" },
  { key: "named_team", label: "Named team members" },
];

function number(value: number | null | undefined, suffix = ""): string {
  return value == null ? "—" : `${value}${suffix}`;
}

function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${value}%`;
}

function chips(items: string[] | undefined): ReactNode {
  if (!items?.length) return <span className="text-[#8A8496]">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((item) => (
        <span
          key={item}
          className="rounded-[8px] bg-[#F4F2F7] px-2 py-0.5 text-[10px] font-semibold text-[#3B2D5E]"
        >
          {item}
        </span>
      ))}
    </span>
  );
}

function factNode(subject: ComparisonSubject, key: FactKey): ReactNode {
  if (!subject.available) return <span className="text-[11px] text-[#8E1230]">{subject.reason}</span>;
  const facts = subject.facts;
  switch (key) {
    case "positive_pct":
    case "negative_pct":
      return <span className="font-mono font-bold">{percent(facts[key])}</span>;
    case "branch":
      return facts.branch ?? <span className="text-[#8A8496]">—</span>;
    case "employee_mentions":
    case "working_hard_mentions":
    case "menu_price_mentions":
    case "parking_praised":
    case "parking_criticised":
      return <span className="font-mono font-bold">{number(facts[key])}</span>;
    case "services":
    case "top_problems":
      return chips(facts[key]);
    case "named_team":
      if (!facts.named_team.length) return <span className="text-[#8A8496]">—</span>;
      return (
        <span className="flex flex-col gap-0.5">
          {facts.named_team.map((member) => (
            <span key={member.name} className="text-[11px]">
              <strong className="font-bold">{member.name}</strong>
              <span className="text-[#3B2D5E]"> · {member.mentions} mentions</span>
            </span>
          ))}
        </span>
      );
    default:
      return "—";
  }
}

function Select({
  side,
  value,
  onChange,
  saved,
  own,
}: {
  side: "left" | "right";
  value: string;
  onChange: (value: string) => void;
  saved: SavedPlace[];
  own: ChannelOption[];
}) {
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1.5">
      <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
        {side === "left" ? "Business A" : "Business B"}
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={`Select ${side === "left" ? "first" : "second"} business`}
        className={`h-11 w-full rounded-[16px] border border-[var(--ui-line)] bg-white px-3 text-[12px] font-semibold text-[#14101F] ${FOCUS}`}
      >
        <option value="">Select a business…</option>
        <optgroup label="Saved businesses">
          {saved.map((place) => (
            <option key={place.id} value={subjectKey("saved", place.place_id)}>
              {place.label || place.name || place.place_id}
            </option>
          ))}
        </optgroup>
        <optgroup label="Our own business">
          {own.map((channel) => (
            <option key={channel.id} value={subjectKey("own", channel.id)}>
              {channel.display_name || "Unnamed location"}
            </option>
          ))}
        </optgroup>
      </select>
    </label>
  );
}

function SideHeader({ subject, fallback }: { subject: ComparisonSubject | undefined; fallback: string }) {
  const name = subject?.name || fallback || "Select a business";
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-2">
        <h3 className="truncate text-[14px] font-bold text-[#14101F]" title={name}>{name}</h3>
        {subject?.available ? (
          <VerificationBadge status={subject.verified ? "verified" : "unstarted"} compact />
        ) : null}
      </div>
      <p className="mt-0.5 truncate text-[10px] text-[#3B2D5E]">
        {subject?.address
          ? subject.address
          : subject
          ? subject.data_source === "google_places"
            ? "Google Places listing"
            : "Your connected location"
          : "Choose two businesses above"}
      </p>
    </div>
  );
}

export default function ComparePage() {
  const router = useRouter();
  const params = useSearchParams();
  const leftKey = params.get("left") ?? "";
  const rightKey = params.get("right") ?? "";

  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const saved = savedQuery.data ?? [];
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

  const compareQuery = useQuery({
    queryKey: ["benchmark", "compare", leftKey, rightKey],
    queryFn: () => fetchComparison([leftKey, rightKey]),
    enabled: Boolean(leftKey && rightKey),
  });
  const subjects = compareQuery.data?.subjects ?? [];
  const left = subjects[0];
  const right = subjects[1];

  function update(side: "left" | "right", value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(side, value);
    else next.delete(side);
    router.replace(`/dashboard/benchmark/compare?${next.toString()}`, { scroll: false });
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
            Two businesses. One honest picture.
          </h1>
          <p className="mt-3 max-w-lg text-[13px] leading-relaxed text-[#3B2D5E]">
            Put any saved competitor next to any of your own branches. Compare the
            numbers Google actually publishes, then read what customers say about
            the team, the menu, parking and service — side by side, with nothing
            invented to fill the gaps.
          </p>
        </div>
        <div className="relative hidden min-h-[220px] items-center justify-center lg:flex">
          <div className="absolute left-[12%] top-[16%] h-24 w-40 rounded-[16px] bg-white shadow-[0_2px_8px_rgba(20,16,31,0.08)]" />
          <div className="absolute bottom-[16%] right-[12%] h-24 w-40 rounded-[16px] bg-[#B0338A] shadow-[0_2px_8px_rgba(20,16,31,0.12)]" />
          <div className="relative z-10 flex h-14 w-14 items-center justify-center rounded-full border-[3px] border-white bg-[#3D1D6E] text-[15px] font-extrabold text-white shadow-[0_2px_8px_rgba(20,16,31,0.18)]">
            VS
          </div>
        </div>
      </section>

      {/* Two dropdowns; the second optgroup is the "our own business" divider. */}
      <section className="mt-5 rounded-[16px] border border-[var(--ui-line)] bg-white p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Select side="left" value={leftKey} onChange={(v) => update("left", v)} saved={saved} own={own} />
          <span className="mb-3 shrink-0 self-center text-[12px] font-extrabold text-[#B0338A] sm:mb-2">VS</span>
          <Select side="right" value={rightKey} onChange={(v) => update("right", v)} saved={saved} own={own} />
        </div>
      </section>

      {!leftKey || !rightKey ? (
        <p className="mt-6 rounded-[16px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-10 text-center text-[12px] text-[#3B2D5E]">
          Pick a business on both sides to see the comparison.
        </p>
      ) : compareQuery.isPending ? (
        <p className="mt-6 text-[12px] text-[#3B2D5E]">Loading comparison…</p>
      ) : compareQuery.isError ? (
        <p className="mt-6 text-[12px] text-red-700">Could not load the comparison.</p>
      ) : (
        <>
          {/* Table 1 — hard numbers from Google. */}
          <section className="mt-5 overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white">
            <div className="grid grid-cols-[minmax(140px,1fr)_1fr_1fr] gap-2 border-b border-[var(--ui-line)] bg-[#F4F2F7] px-4 py-3">
              <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">Metric</span>
              <SideHeader subject={left} fallback={leftKey} />
              <SideHeader subject={right} fallback={rightKey} />
            </div>
            <div className="divide-y divide-[var(--ui-line)]">
              {METRIC_ROWS.map((row) => {
                const a = left?.available ? left.metrics[row.key] : null;
                const b = right?.available ? right.metrics[row.key] : null;
                const aWins = a != null && b != null && a > b;
                const bWins = b != null && a != null && b > a;
                return (
                  <div key={row.key} className="grid grid-cols-[minmax(140px,1fr)_1fr_1fr] items-center gap-2 px-4 py-2.5">
                    <span className="text-[11px] font-semibold text-[#14101F]">{row.label}</span>
                    <span className={`font-mono text-[12px] ${aWins ? "font-extrabold text-[#B0338A]" : "text-[#3B2D5E]"}`}>
                      {!left?.available ? left?.reason : number(a, row.suffix)}
                    </span>
                    <span className={`font-mono text-[12px] ${bWins ? "font-extrabold text-[#B0338A]" : "text-[#3B2D5E]"}`}>
                      {!right?.available ? right?.reason : number(b, row.suffix)}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Table 2 — facts and review-derived signals, with honest gaps. */}
          <section className="mt-5 overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white">
            <div className="border-b border-[var(--ui-line)] bg-[#F4F2F7] px-4 py-3">
              <h2 className="text-[14px] font-bold text-[#14101F]">What customers say</h2>
              <p className="mt-0.5 text-[10px] text-[#3B2D5E]">
                Review-text signals are scanned from the most recent reviews; owner-only facts stay blank for competitors.
              </p>
            </div>
            <div className="grid grid-cols-[minmax(140px,1fr)_1fr_1fr] gap-2 border-b border-[var(--ui-line)] px-4 py-2.5 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
              <span>Fact</span>
              <span>{left?.name || "Business A"}</span>
              <span>{right?.name || "Business B"}</span>
            </div>
            <div className="divide-y divide-[var(--ui-line)]">
              {FACT_ROWS.map((row) => (
                <div key={row.key} className="grid grid-cols-[minmax(140px,1fr)_1fr_1fr] items-start gap-2 px-4 py-2.5">
                  <span className="text-[11px] font-semibold text-[#14101F]">{row.label}</span>
                  <span className="text-[12px] text-[#3B2D5E]">{left ? factNode(left, row.key) : "—"}</span>
                  <span className="text-[12px] text-[#3B2D5E]">{right ? factNode(right, row.key) : "—"}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-5 grid gap-3 sm:grid-cols-2">
            {[left, right].filter((s): s is ComparisonSubject => Boolean(s)).map((subject) => (
              <div key={subject.key} className="rounded-[16px] border border-[var(--ui-line)] bg-white p-4">
                <h3 className="text-[12px] font-bold text-[#14101F]">{subject.name || subject.id}</h3>
                <ul className="mt-2 list-disc pl-4 text-[10px] leading-relaxed text-[#3B2D5E]">
                  {subject.notes.map((note) => <li key={note}>{note}</li>)}
                </ul>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}
