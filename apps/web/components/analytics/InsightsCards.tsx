"use client";

import Link from "next/link";
import type { InsightsCards, ThemeCard } from "@/lib/api-analytics";

function Trend({ value }: { value: number | null }) {
  if (value === null) return <span className="text-[10px] text-[var(--ui-ink-2)]">new</span>;
  const up = value > 0;
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-[2px] px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${up ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
      {up ? "+" : ""}{value}%
    </span>
  );
}

function themeLabel(name: string): string {
  return name.replace(/_/g, " ");
}

function ThemeRow({ theme }: { theme: ThemeCard }) {
  return (
    <li className="py-3 first:pt-1 last:pb-1">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold capitalize text-[var(--ui-ink)]">{theme.name}</span>
        <span className="shrink-0 text-[11px] tabular-nums text-[var(--ui-ink-2)]">{theme.mentions}</span>
        <Trend value={theme.trend_pct} />
      </div>
      <p className="mt-0.5 text-[10px] text-[var(--ui-ink-2)]">
        {theme.negative_pct}% negative
        {theme.top_location ? ` · mostly ${theme.top_location}` : ""}
      </p>
      {theme.quote && (
        <p className="mt-1 truncate text-[11px] italic text-[var(--ui-ink-2)]">&ldquo;{theme.quote}&rdquo;</p>
      )}
    </li>
  );
}

export default function InsightsCardsSection({
  cards,
  loading,
}: {
  cards: InsightsCards | null;
  loading: boolean;
}) {
  if (loading || !cards) {
    return (
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <div className="ui-card h-48 animate-pulse" aria-hidden />
        <div className="ui-card h-48 animate-pulse" aria-hidden />
      </div>
    );
  }

  const changed = cards.what_changed;
  const summary = cards.summary;
  const themes = cards.top_themes ?? [];
  const locations = cards.sentiment_by_location ?? [];
  const actions = cards.action_plan ?? [];

  return (
    <div className="space-y-4 sm:space-y-5">
      {/* Top themes + what changed */}
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
        <section aria-label="Top themes" className="ui-card p-5 lg:col-span-2">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Top themes</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">What customers talk about, with the count and a verbatim quote.</p>
          {themes.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">No themes yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-[var(--ui-line)]">
              {themes.map((t) => <ThemeRow key={t.name} theme={t} />)}
            </ul>
          )}
        </section>

        <section aria-label="What changed this week" className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">What changed this week</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">Low-star reviews vs the prior 7 days.</p>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-[30px] font-black leading-none tabular-nums text-[var(--ui-ink)]">{changed.low_reviews}</span>
            <span className="text-[12px] font-semibold text-[var(--ui-ink-2)]">low-star</span>
            <Trend value={changed.prior_low_reviews === 0 ? null : Math.round(((changed.low_reviews - changed.prior_low_reviews) / changed.prior_low_reviews) * 100)} />
          </div>
          <p className="mt-1 text-[10px] text-[var(--ui-ink-2)]">prior week: {changed.prior_low_reviews}</p>
          {changed.theme && (
            <p className="mt-3 text-[12px] text-[var(--ui-ink)]">
              Main theme: <strong className="capitalize">{themeLabel(changed.theme)}</strong>
              {changed.location ? ` · ${changed.location}` : ""}
            </p>
          )}
          {changed.example && (
            <p className="mt-1 truncate text-[11px] italic text-[var(--ui-ink-2)]">&ldquo;{changed.example}&rdquo;</p>
          )}
          <Link href="/dashboard/reviews?status=unanswered" className="mt-3 inline-block text-[11px] font-bold text-[var(--ui-ink)] underline underline-offset-2">
            Review the low-star reviews
          </Link>
        </section>
      </div>

      {/* Sentiment by location + summary */}
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
        <section aria-label="Sentiment by location" className="ui-card p-5 lg:col-span-2">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Sentiment by location</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">Rating trend (90d), top complaint, response rate, and outstanding replies.</p>
          {locations.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">No location data.</p>
          ) : (
            <ul className="mt-2 divide-y divide-[var(--ui-line)]">
              {locations.map((l) => (
                <li key={l.channel_id} className="flex flex-wrap items-center gap-2 py-2.5 first:pt-1 last:pb-1">
                  <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{l.name}</span>
                  <span className="shrink-0 text-[11px] font-bold tabular-nums text-[var(--ui-ink)]">
                    {l.avg_rating !== null ? l.avg_rating.toFixed(1) : "-"}&#9733;
                  </span>
                  <span className={`w-12 shrink-0 text-right text-[10px] font-semibold tabular-nums ${(l.rating_trend ?? 0) < 0 ? "text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}`}>
                    {l.rating_trend === null ? "new" : `${l.rating_trend > 0 ? "+" : ""}${l.rating_trend}`}
                  </span>
                  <span className="w-28 shrink-0 truncate text-[10px] text-[var(--ui-ink-2)]">{l.top_negative_theme ? themeLabel(l.top_negative_theme) : "no complaint"}</span>
                  <span className="w-12 shrink-0 text-right text-[10px] tabular-nums text-[var(--ui-ink-2)]">{l.response_rate}%</span>
                  <span className={`w-16 shrink-0 text-right text-[10px] tabular-nums ${l.unanswered > 0 ? "font-bold text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}`}>
                    {l.unanswered} waiting
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Summary with receipts" className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Summary with receipts</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">Generated from {summary.review_count} reviews · confidence: {summary.confidence}.</p>
          {summary.bullets.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">Not enough data to summarize.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {summary.bullets.map((b, i) => (
                <li key={i} className="flex items-start gap-2 text-[12px] text-[var(--ui-ink)]">
                  <span className="mt-0.5 shrink-0 rounded-[2px] bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[9px] font-bold tabular-nums text-[var(--ui-ink)]">n={b.n}</span>
                  <span>{b.text}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
            Data-derived, not a model narrative. Every bullet shows its count.
          </p>
        </section>
      </div>

      {/* Action plan */}
      <section aria-label="Action plan" className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Action plan</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">Tracked issues and their fixes, worst first.</p>
          </div>
          <Link href="/dashboard/reviews/issues" className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]">
            All issues
          </Link>
        </div>
        {actions.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">No open issues. Create one from a review on the Reviews page.</p>
        ) : (
          <ul className="mt-3 divide-y divide-[var(--ui-line)]">
            {actions.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 py-2.5 first:pt-0 last:pb-0">
                <span className={`shrink-0 rounded-[2px] px-1.5 py-0.5 text-[9px] font-bold uppercase ${a.status === "in_progress" ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                  {a.status.replace(/_/g, " ")}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{a.title || themeLabel(a.subject)}</span>
                <span className="shrink-0 text-[10px] text-[var(--ui-ink-2)]">{a.negative_count} complaints</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
