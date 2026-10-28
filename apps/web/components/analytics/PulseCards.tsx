"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { fetchPulse, type PulseResponse } from "@/lib/api-analytics";

const PLATFORM_LABEL: Record<string, string> = {
  google_reviews: "Google",
  google: "Google",
  facebook: "Facebook",
  instagram: "Instagram",
  whatsapp: "WhatsApp",
};

function platformLabel(p: string): string {
  return PLATFORM_LABEL[p] ?? p.replace(/_/g, " ");
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function fmtAgo(iso: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function DeltaChip({ value, suffix = "" }: { value: number | null; suffix?: string }) {
  if (value === null || value === undefined) {
    return <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--ui-ink-2)]">no prior data</span>;
  }
  const up = value > 0;
  const flat = value === 0;
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-[2px] px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${flat ? "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]" : up ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
      {!flat && (
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2.5 w-2.5 ${up ? "" : "rotate-180"}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {up ? "+" : ""}{value}{suffix}
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{label}</p>
      <p className="mt-0.5 truncate text-[16px] font-black tabular-nums text-[var(--ui-ink)]">{value}</p>
      {sub && <p className="truncate text-[10px] text-[var(--ui-ink-2)]">{sub}</p>}
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="ui-card p-5" aria-hidden>
      <div className="h-3 w-28 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" />
      <div className="mt-3 h-8 w-20 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" />
      <div className="mt-4 grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" />)}
      </div>
    </div>
  );
}

export default function PulseCards({
  days,
  channelId,
}: {
  days: number;
  channelId: string | null;
}) {
  const query = useQuery({
    queryKey: queryKeys.analytics.pulse(days, channelId),
    queryFn: () => fetchPulse(days, channelId),
    staleTime: 30 * 1000,
  });

  if (query.isPending) {
    return (
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="ui-card p-4">
        <p className="text-[12px] font-semibold text-[var(--ui-ink-2)]">Could not load the reputation pulse.</p>
      </div>
    );
  }

  const data: PulseResponse = query.data;
  const rep = data.reputation;
  const waiting = data.waiting;
  const synced = fmtAgo(rep.last_synced_at);
  const waitingAsOf = fmtAgo(waiting.as_of);
  const sourcesText = rep.sources.length
    ? rep.sources.map((s) => `${platformLabel(s.platform)} ${s.count}`).join(" · ")
    : "No reviews in this period";

  return (
    <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
      {/* Reputation pulse */}
      <section aria-label="Reputation pulse" className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Reputation pulse</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">Last {days} days vs the prior {days}.</p>
          </div>
          {rep.awaiting_reply > 0 && (
            <Link
              href="/dashboard/reviews?status=unanswered"
              className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
            >
              Reply to {rep.awaiting_reply}
            </Link>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex items-baseline gap-1">
            <span className="text-[34px] font-black leading-none tabular-nums text-[var(--ui-ink)]">
              {rep.avg_rating > 0 ? rep.avg_rating.toFixed(1) : "-"}
            </span>
            <span className="text-[16px] font-bold text-[var(--ui-ink-2)]">&#9733;</span>
          </div>
          <DeltaChip value={rep.rating_delta} />
          <span className="text-[10px] text-[var(--ui-ink-2)]">vs prior {days}d</span>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[var(--ui-line)] pt-3">
          <Stat label="New reviews" value={String(rep.new_reviews)} sub={rep.new_reviews_delta_pct !== null ? `${rep.new_reviews_delta_pct > 0 ? "+" : ""}${rep.new_reviews_delta_pct}% vs prior` : "no prior data"} />
          <Stat label="Responded" value={`${rep.response_rate}%`} sub="of period reviews" />
          <Stat label="Awaiting reply" value={String(rep.awaiting_reply)} sub={rep.oldest_wait_days !== null ? `oldest ${rep.oldest_wait_days}d` : "all clear"} />
        </div>

        <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
          {sourcesText}
          {synced ? ` · synced ${synced}` : ""}
        </p>
      </section>

      {/* Who's waiting */}
      <section aria-label="Who is waiting" className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Who&apos;s waiting</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">Unanswered conversations across channels.</p>
          </div>
          <Link
            href="/dashboard/channels/inbox"
            className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
          >
            Open inbox
          </Link>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[34px] font-black leading-none tabular-nums text-[var(--ui-ink)]">
              {waiting.unanswered_texts}
            </span>
            <span className="pb-0.5 text-[12px] font-semibold text-[var(--ui-ink-2)]">
              {waiting.unanswered_texts === 1 ? "conversation waiting" : "conversations waiting"}
            </span>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[var(--ui-line)] pt-3">
          <Stat label="Median first reply" value={fmtDuration(waiting.median_first_response_seconds)} sub={`last ${days} days`} />
          <Stat label="Waiting > 1h" value={String(waiting.waiting_over_1h)} sub={waiting.waiting_over_1h === 1 ? "channel" : "channels"} />
          <Stat
            label="Missed calls"
            value={waiting.missed_calls_available && waiting.missed_calls !== null ? String(waiting.missed_calls) : "-"}
            sub={waiting.missed_calls_available ? "business hours" : "calls not connected"}
          />
        </div>

        <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
          {waiting.oldest_unanswered_seconds !== null
            ? `Oldest waiting ${fmtDuration(waiting.oldest_unanswered_seconds)}`
            : "Nothing waiting"}
          {waitingAsOf ? ` · as of ${waitingAsOf}` : ""}
        </p>
      </section>
    </div>
  );
}
