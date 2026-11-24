"use client";

/* eslint-disable @next/next/no-img-element -- reviewer photos are dynamic remote URLs; native loading preserves the no-referrer privacy boundary used by benchmark review cards. */

import { useId, useState, type CSSProperties, type ReactNode } from "react";
import LogoLoader from "@/components/LogoLoader";
import Modal from "@/components/dashboard/media/Modal";
import type {
  ReviewThemeCell,
  ReviewThemeQuote,
  ReviewThemeRow,
  ReviewThemeSentiment,
  ReviewThemeSubject,
  ReviewThemesResponse,
} from "@/lib/api-benchmark";
import { LOW_SAMPLE_THRESHOLD, median } from "@/lib/benchmark-chart-data";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";
import { safeHref } from "@/lib/safe-url";

const FOCUS =
  "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-[#3D1D6E]";
const MAX_QUOTE_CARDS = 6;

type ThemeFilter = "all" | "positive" | "negative";
type ReviewKeywordCopy = Dict["benchmark"]["compare"]["reviewKeywords"];

interface ReviewKeywordsProps {
  data: ReviewThemesResponse | undefined;
  mainKey: string | null;
  loading: boolean;
  fetching: boolean;
  error: unknown;
  onRetry: () => void;
}

interface QuoteSelection {
  row: ReviewThemeRow;
  subject: ReviewThemeSubject;
  cell: ReviewThemeCell;
}

function formatPercent(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value * 10) / 10}%`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function initials(name: string | null): string {
  return (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "?";
}

function HighlightedReview({ quote, text }: { quote: string; text: string }) {
  const index = quote ? text.indexOf(quote) : -1;
  if (index < 0) return <p dir="auto" className="whitespace-pre-wrap">{text}</p>;
  return (
    <p dir="auto" className="whitespace-pre-wrap">
      {text.slice(0, index)}
      <mark className="rounded-[3px] bg-[#FFF0B3] px-0.5 text-[#14101F]">{quote}</mark>
      {text.slice(index + quote.length)}
    </p>
  );
}

function ReviewAvatar({ name, photo }: { name: string | null; photo: string | null }) {
  const [failed, setFailed] = useState(false);
  const safePhoto = safeHref(photo ?? "");
  if (safePhoto && !failed) {
    return (
      <img
        src={safePhoto}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className="h-9 w-9 shrink-0 rounded-full border border-[var(--ui-line)] object-cover"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#F4F2F7] text-[11px] font-bold text-[#3D1D6E]"
    >
      {initials(name)}
    </span>
  );
}

function QuoteCard({ quote, business }: { quote: ReviewThemeQuote; business: string }) {
  const { t } = useI18n();
  const k = t.benchmark.compare.reviewKeywords;
  const reviewUrl = safeHref(quote.review_url ?? "");
  return (
    <article className="rounded-[8px] border border-[var(--ui-line)] bg-white p-4 shadow-[0_2px_8px_rgba(20,16,31,0.06)]">
      <div className="flex items-start gap-3">
        <ReviewAvatar name={quote.author} photo={quote.author_photo} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12px] font-bold text-[#14101F]">
            {quote.author || k.reviewer}
          </p>
          <p className="mt-0.5 text-[10px] text-[#6F6685]">{business}</p>
        </div>
        <span className="shrink-0 rounded-[8px] bg-[#F4F2F7] px-2 py-1 text-[11px] font-bold text-[#3B2D5E]">
          {quote.rating == null ? k.noRating : `${quote.rating}★`}
        </span>
      </div>
      <div className="mt-3 text-[13px] leading-relaxed text-[#14101F]">
        <HighlightedReview quote={quote.quote} text={quote.review_text} />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--ui-line)] pt-3">
        <time dateTime={quote.reviewed_at ?? undefined} className="font-mono text-[10px] text-[#6F6685]">
          {formatDate(quote.reviewed_at)}
        </time>
        {reviewUrl ? (
          <a
            href={reviewUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex min-h-9 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[10px] font-bold text-[#3D1D6E] transition active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
          >
            {k.viewOnGoogle}
          </a>
        ) : null}
      </div>
    </article>
  );
}

function QuoteDialog({ selection, onClose }: { selection: QuoteSelection; onClose: () => void }) {
  const { t } = useI18n();
  const k = t.benchmark.compare.reviewKeywords;
  const business = selection.subject.name ?? selection.subject.key;
  const percentage = formatPercent(selection.cell.percentage);
  const quotes = selection.cell.quotes.slice(0, MAX_QUOTE_CARDS);
  return (
    <Modal
      open
      onClose={onClose}
      title={k.quotesTitle(selection.row.label)}
      subtitle={k.quotesSubtitle(business, selection.cell.mentions, selection.cell.sample_size, percentage)}
      closeLabel={k.close}
      width="max-w-[720px]"
    >
      <p className="text-[10px] font-bold uppercase tracking-wide text-[#6F6685]">{k.quoteEvidence}</p>
      <div className="mt-3 flex flex-col gap-3">
        {quotes.map((quote) => (
          <QuoteCard key={quote.review_id} quote={quote} business={business} />
        ))}
      </div>
      {selection.cell.quotes.length > quotes.length ? (
        <p className="mt-3 text-[10px] text-[#6F6685]">
          {k.showingQuotes(quotes.length, selection.cell.quotes.length)}
        </p>
      ) : null}
    </Modal>
  );
}

const SENTIMENT_CLASS: Record<ReviewThemeSentiment, string> = {
  positive: "bg-[#3D1D6E] text-white",
  negative: "bg-[#FF4F6E] text-[#14101F]",
  mixed: "bg-[#B0338A] text-white",
};

function SentimentLabel({ sentiment }: { sentiment: ReviewThemeSentiment }) {
  const { t } = useI18n();
  const k = t.benchmark.compare.reviewKeywords;
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[9px] font-bold ${SENTIMENT_CLASS[sentiment]}`}>
      {k[sentiment]}
    </span>
  );
}

function ThemeCell({
  row,
  subject,
  cell,
  onOpenQuotes,
}: {
  row: ReviewThemeRow;
  subject: ReviewThemeSubject;
  cell: ReviewThemeCell;
  onOpenQuotes: () => void;
}) {
  const { t } = useI18n();
  const k = t.benchmark.compare.reviewKeywords;
  const business = subject.name ?? subject.key;
  const percentage = formatPercent(cell.percentage);
  const barWidth = `${Math.min(100, Math.max(0, cell.percentage))}%`;
  return (
    <div className="min-w-0">
      <p className="font-mono text-[11px] font-bold text-[#14101F]">
        {k.mentions(cell.mentions, cell.sample_size, percentage)}
      </p>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[#EFEDF2]">
        <div
          role="img"
          aria-label={k.barLabel(row.label, business)}
          className={`h-full rounded-full ${SENTIMENT_CLASS[row.sentiment]}`}
          style={{ width: barWidth }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <SentimentLabel sentiment={row.sentiment} />
        {cell.quotes.length > 0 ? (
          <button
            type="button"
            onClick={onOpenQuotes}
            aria-label={k.quoteButton(row.label, business, cell.mentions, cell.sample_size, percentage)}
            className={`inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-2 text-[10px] font-bold text-[#3D1D6E] transition active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
          >
            {k.openQuotes}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function SubjectStatus({ subject, onRetry }: { subject: ReviewThemeSubject; onRetry: () => void }) {
  const { t } = useI18n();
  const k = t.benchmark.compare.reviewKeywords;
  if (subject.status === "pending") {
    return <span role="status" className="text-[11px] font-semibold text-[#6F6685]">{k.analyzing}</span>;
  }
  if (subject.status === "unavailable") {
    return <span className="text-[11px] font-semibold text-[#6F6685]">{k.unavailable}</span>;
  }
  if (subject.status === "error") {
    return (
      <div>
        <p className="text-[11px] font-semibold text-[#B3123A]">{k.subjectError}</p>
        <button
          type="button"
          onClick={onRetry}
          aria-label={k.retryBusiness(subject.name ?? subject.key)}
          className={`mt-1 inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-2 text-[10px] font-bold text-[#3D1D6E] transition active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
        >
          {k.retry}
        </button>
      </div>
    );
  }
  return null;
}

function subjectRole(subject: ReviewThemeSubject, mainKey: string | null, k: ReviewKeywordCopy): string {
  if (subject.key !== mainKey) return subject.kind === "own" ? k.yourLocation : k.googleListing;
  return subject.kind === "own" ? k.yourBranch : k.selectedBusiness;
}

/** Missing cells on a ready subject are genuine zero mentions, not missing data. */
function readyCell(row: ReviewThemeRow, subject: ReviewThemeSubject): ReviewThemeCell {
  return row.cells[subject.key] ?? {
    mentions: 0,
    sample_size: subject.sample_size,
    percentage: 0,
    positive: 0,
    negative: 0,
    quotes: [],
  };
}

function rowComparison(
  row: ReviewThemeRow,
  subjects: ReviewThemeSubject[],
  mainKey: string | null,
  k: ReviewKeywordCopy,
): ReactNode {
  const ready = subjects.filter((subject) => subject.status === "ready");
  const peerMedian = row.peer_median_pct ?? median(
    ready.filter((subject) => subject.key !== mainKey).map((subject) => readyCell(row, subject).percentage),
  );
  const main = mainKey ? ready.find((subject) => subject.key === mainKey) : undefined;
  const own = row.own_pct ?? (main ? readyCell(row, main).percentage : null);
  const gap = row.gap_pct ?? (own != null && peerMedian != null ? own - peerMedian : null);
  return (
    <span className="mt-1 block text-[9px] font-normal leading-relaxed text-[#6F6685]">
      <span className="block">{peerMedian == null ? k.noPeerMedian : k.peerMedian(formatPercent(peerMedian))}</span>
      <span className="block">
        {gap == null
          ? k.noOwnGap
          : Math.abs(gap) < 0.05
            ? k.gapFlat
            : gap > 0
              ? k.gapAbove(formatPercent(Math.abs(gap)).replace("%", ""))
              : k.gapBelow(formatPercent(Math.abs(gap)).replace("%", ""))}
      </span>
    </span>
  );
}

export default function ReviewKeywords({
  data,
  mainKey,
  loading,
  fetching,
  error,
  onRetry,
}: ReviewKeywordsProps) {
  const { t } = useI18n();
  const k = t.benchmark.compare.reviewKeywords;
  const titleId = useId();
  const [filter, setFilter] = useState<ThemeFilter>("all");
  const [mobileKey, setMobileKey] = useState<string | null>(mainKey);
  const [quoteSelection, setQuoteSelection] = useState<QuoteSelection | null>(null);
  const subjects = data?.subjects ?? [];
  const selectedMobileKey = subjects.some((subject) => subject.key === mobileKey)
    ? mobileKey
    : subjects.find((subject) => subject.key === mainKey)?.key ?? subjects[0]?.key ?? null;
  const readyCount = subjects.filter((subject) => subject.status === "ready").length;
  const pendingCount = subjects.filter((subject) => subject.status === "pending").length;
  const visibleRows = (data?.rows ?? []).filter(
    (row) => filter === "all" || row.sentiment === filter,
  );

  return (
    <section aria-labelledby={titleId} className="mt-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={titleId} className="text-[16px] font-bold text-[#14101F]">{k.title}</h2>
          <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-[#3B2D5E]">{k.description}</p>
        </div>
        {fetching && !loading ? (
          <span role="status" className="rounded-full bg-[#F4F2F7] px-2.5 py-1 text-[10px] font-semibold text-[#6F6685]">
            {k.refreshing}
          </span>
        ) : null}
      </header>

      {error ? (
        <div role="alert" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[8px] border border-[#FF4F6E]/35 bg-white px-3 py-2">
          <p className="text-[11px] font-semibold text-[#B3123A]">{k.wholeError}</p>
          <button
            type="button"
            onClick={onRetry}
            className={`inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[10px] font-bold text-[#3D1D6E] transition active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
          >
            {k.retry}
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="mt-3 flex justify-center rounded-[8px] border border-[var(--ui-line)] bg-white px-4 py-10">
          <LogoLoader size={36} label={k.loading} showText />
        </div>
      ) : data ? (
        <>
          {pendingCount > 0 ? (
            <p role="status" className="mt-3 rounded-[8px] border border-[#3D1D6E]/20 bg-[#F3EEFB] px-3 py-2 text-[11px] font-semibold text-[#3D1D6E]">
              {k.pendingBanner(pendingCount)}
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
            <div role="group" aria-label={k.filterLabel} className="flex flex-wrap gap-1.5">
              {(["all", "positive", "negative"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                  className={`min-h-11 rounded-[8px] border px-3 text-[11px] font-bold transition active:translate-y-[2px] active:scale-[0.98] ${FOCUS} ${
                    filter === value
                      ? "border-[#3D1D6E] bg-[#3D1D6E] text-white"
                      : "border-[var(--ui-line)] bg-white text-[#3B2D5E] hover:bg-[#F4F2F7]"
                  }`}
                >
                  {k[value]}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 md:hidden">
              <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{k.business}</span>
              <select
                value={selectedMobileKey ?? ""}
                onChange={(event) => setMobileKey(event.target.value)}
                className={`min-w-0 flex-1 rounded-[8px] border border-[var(--ui-line)] bg-white px-2 py-1.5 text-[11px] font-semibold text-[#14101F] ${FOCUS}`}
              >
                {subjects.map((subject) => (
                  <option key={subject.key} value={subject.key}>{subject.name ?? subject.key}</option>
                ))}
              </select>
            </label>
          </div>

          <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {subjects.map((subject) => (
              <li key={subject.key} className={`rounded-[8px] border bg-white px-3 py-2 ${subject.key === mainKey ? "border-[#3D1D6E]/35" : "border-[var(--ui-line)]"}`}>
                <div className="flex flex-wrap items-center justify-between gap-1">
                  <span dir="auto" className="truncate text-[11px] font-bold text-[#14101F]">{subject.name ?? subject.key}</span>
                  {subject.status === "ready" && subject.sample_size < LOW_SAMPLE_THRESHOLD ? (
                    <span className="rounded-full bg-[#FFF3D6] px-2 py-0.5 text-[9px] font-bold text-[#8A6100]">{k.lowSample}</span>
                  ) : null}
                </div>
                <p className="mt-0.5 font-mono text-[10px] text-[#6F6685]">{k.sampleSize(subject.sample_size)}</p>
              </li>
            ))}
          </ul>

          {visibleRows.length > 0 ? (
            <div className="mt-3 overflow-x-auto rounded-[8px] border border-[var(--ui-line)] bg-white">
              <table
                className="w-full table-fixed border-collapse text-start min-w-[360px] md:min-w-[var(--review-table-min)]"
                style={{ "--review-table-min": `${240 + subjects.length * 200}px` } as CSSProperties}
              >
                <caption className="sr-only">{k.title}</caption>
                <colgroup>
                  <col style={{ width: 240 }} />
                  {subjects.map((subject) => (
                    <col
                      key={subject.key}
                      className={selectedMobileKey === subject.key ? "" : "hidden md:table-column"}
                    />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" style={{ insetInlineStart: 0 }} className="sticky z-20 border-b border-e border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">
                      {k.themeComparison}
                    </th>
                    {subjects.map((subject) => (
                      <th
                        key={subject.key}
                        scope="col"
                        data-mobile-selected={selectedMobileKey === subject.key}
                        className={`border-b border-e border-[var(--ui-line)] px-3 py-2 last:border-e-0 ${
                          selectedMobileKey === subject.key ? "" : "hidden md:table-cell"
                        } ${subject.key === mainKey ? "bg-[#F3EEFB]" : "bg-[#FAFAFB]"}`}
                      >
                        <span dir="auto" className="block truncate text-[11px] font-bold text-[#14101F]" title={subject.name ?? undefined}>
                          {subject.name ?? subject.key}
                        </span>
                        <span className="mt-0.5 block text-[9px] font-semibold text-[#6F6685]">
                          {subjectRole(subject, mainKey, k)}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr key={row.key}>
                      <th scope="row" style={{ insetInlineStart: 0 }} className="sticky z-10 border-b border-e border-[var(--ui-line)] bg-white px-3 py-3 text-start align-top">
                        <span dir="auto" className="block text-[11px] font-bold text-[#14101F]">{row.label}</span>
                        {rowComparison(row, subjects, mainKey, k)}
                      </th>
                      {subjects.map((subject) => {
                        const selected = selectedMobileKey === subject.key;
                        const cell = readyCell(row, subject);
                        return (
                          <td
                            key={subject.key}
                            className={`border-b border-e border-[var(--ui-line)] px-3 py-3 align-top last:border-e-0 ${
                              selected ? "" : "hidden md:table-cell"
                            } ${subject.key === mainKey ? "bg-[#F8F6FB]" : "bg-white"}`}
                          >
                            {subject.status === "ready" ? (
                              <ThemeCell
                                row={row}
                                subject={subject}
                                cell={cell}
                                onOpenQuotes={() => setQuoteSelection({ row, subject, cell })}
                              />
                            ) : (
                              <SubjectStatus subject={subject} onRetry={onRetry} />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="mt-3 rounded-[8px] border border-dashed border-[var(--ui-line)] bg-white px-4 py-6 text-center">
              <p className="text-[12px] font-semibold text-[#3B2D5E]">
                {data.rows.length === 0 && readyCount === 0
                  ? k.noReady
                  : data.rows.length === 0 && pendingCount > 0
                    ? k.pendingEmpty
                    : data.rows.length === 0
                      ? k.empty
                      : k.emptyFilter(k[filter])}
              </p>
              {data.rows.length === 0 && subjects.some((subject) => subject.status !== "ready") ? (
                <ul className="mt-3 flex flex-wrap justify-center gap-3">
                  {subjects.filter((subject) => subject.status !== "ready").map((subject) => (
                    <li key={subject.key} className="text-left">
                      <p dir="auto" className="text-[11px] font-bold text-[#14101F]">{subject.name ?? subject.key}</p>
                      <SubjectStatus subject={subject} onRetry={onRetry} />
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </>
      ) : !error ? (
        <p className="mt-3 rounded-[8px] border border-dashed border-[var(--ui-line)] bg-white px-4 py-6 text-center text-[12px] text-[#3B2D5E]">{k.noReady}</p>
      ) : null}

      {quoteSelection ? <QuoteDialog selection={quoteSelection} onClose={() => setQuoteSelection(null)} /> : null}
    </section>
  );
}
