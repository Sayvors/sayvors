"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject, HistoryPoint, SubjectReviews } from "@/lib/api-benchmark";

function pct(n: number, total: number): number { return total > 0 ? (n / total) * 100 : 0; }

function Sparkline({ points, color }: { points: number[]; color: string }) {
  if (points.length < 2) return <div className="h-10 rounded-[8px] bg-[#F4F2F7]" />;
  const W = 120, H = 40;
  const min = Math.min(...points), max = Math.max(...points), span = Math.max(max - min, 0.0001);
  const coords = points.map((v, i) => { const x = (i / (points.length - 1)) * W; const y = H - ((v - min) / span) * (H - 6) - 3; return `${x.toFixed(1)},${y.toFixed(1)}`; });
  return <svg viewBox={`0 0 ${W} ${H}`} className="h-10 w-full" aria-hidden><polyline fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" points={coords.join(" ")} />{coords.length ? <circle cx={coords[coords.length - 1].split(",")[0]} cy={coords[coords.length - 1].split(",")[1]} r="3" fill={color} /> : null}</svg>;
}

export default function BenchmarkStoryCharts({ subjects, mainKey, reviewSubjects, historyBySubject }: { subjects: ComparisonSubject[]; mainKey?: string | null; reviewSubjects: SubjectReviews[]; historyBySubject: Record<string, HistoryPoint[]> }) {
  const { t } = useI18n();
  const s = t.benchmark.story;
  const available = subjects.filter((x) => x.available);
  const own = available.find((x) => x.key === mainKey) ?? available.find((x) => x.kind === "own");
  if (!own) return null;
  const ownReview = reviewSubjects.find((x) => x.key === own.key);
  const responseRate = ownReview?.summary.response_rate ?? null;
  const leaderRating = Math.max(...available.map((x) => x.metrics.avg_rating ?? 0), 0);
  const ratingGap = typeof own.metrics.avg_rating === "number" && leaderRating > 0 ? leaderRating - own.metrics.avg_rating : null;
  const ownHistory = (historyBySubject[own.key] ?? []).map((p) => p.rating).filter((v): v is number => typeof v === "number");
  const neutralPct = (own.facts.positive_pct ?? 0) + (own.facts.negative_pct ?? 0) > 0 ? Math.max(0, 100 - (own.facts.positive_pct ?? 0) - (own.facts.negative_pct ?? 0)) : null;
  const mixRows = [own, ...available.filter((x) => x.key !== own.key).slice(0, 3)];

  return (
    <section aria-labelledby="story-charts-title" className="mt-4">
      <h2 id="story-charts-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{s.title}</h2>
      <p className="mt-0.5 text-[11px] text-[#3B2D5E]">{s.desc}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <article className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{s.ratingGap}</p>
          <p className="mt-1 text-[22px] font-bold text-[#14101F]">{ratingGap == null ? "—" : ratingGap <= 0 ? "Leader" : ratingGap.toFixed(1)}</p>
          <p className="text-[10px] text-[#3B2D5E]">{ratingGap != null && ratingGap > 0 ? s.starsBehindLeader : s.vsTopCompetitor}</p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#F1F2F5]"><div className="h-full rounded-full bg-[#FF4F6E]" style={{ width: `${Math.max(0, Math.min(100, ((own.metrics.avg_rating ?? 0) / 5) * 100))}%` }} /></div>
          <p className="mt-1 text-[10px] text-[#3B2D5E]">{s.yourRating}: {own.metrics.avg_rating?.toFixed(1) ?? "—"} / 5</p>
        </article>
        <article className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{s.responseHealth}</p>
          <p className="mt-1 text-[22px] font-bold text-[#14101F]">{responseRate == null ? "—" : `${Math.round(responseRate)}%`}</p>
          <p className="text-[10px] text-[#3B2D5E]">{s.repliesInSample}</p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#F1F2F5]"><div className="h-full rounded-full bg-[#3D1D6E]" style={{ width: `${Math.max(0, Math.min(100, responseRate ?? 0))}%` }} /></div>
          <p className="mt-1 text-[10px] text-[#3B2D5E]">{ownReview ? `${ownReview.summary.answered}/${ownReview.summary.sampled} ${s.answered}` : s.noSample}</p>
        </article>
        <article className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{s.sentimentMix}</p>
          <p className="mt-1 text-[22px] font-bold text-[#14101F]">{own.facts.positive_pct == null ? "—" : `${Math.round(own.facts.positive_pct)}%`}</p>
          <p className="text-[10px] text-[#3B2D5E]">{s.positive}</p>
          <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-[#F1F2F5]" aria-hidden><div className="bg-[#116631]" style={{ width: `${Math.max(0, own.facts.positive_pct ?? 0)}%` }} /><div className="bg-[#D8D8DC]" style={{ width: `${Math.max(0, neutralPct ?? 0)}%` }} /><div className="bg-[#B3123A]" style={{ width: `${Math.max(0, own.facts.negative_pct ?? 0)}%` }} /></div>
          <div className="mt-1 flex gap-2 text-[9px] text-[#3B2D5E]"><span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#116631]" />{s.pos}</span><span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#D8D8DC]" />{s.neu}</span><span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#B3123A]" />{s.neg}</span></div>
        </article>
        <article className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{s.ratingMomentum}</p>
          <p className="mt-1 text-[22px] font-bold text-[#14101F]">{ownHistory.length >= 2 ? `${(ownHistory[ownHistory.length - 1] - ownHistory[0] > 0 ? "+" : "")}${(ownHistory[ownHistory.length - 1] - ownHistory[0]).toFixed(1)}` : "—"}</p>
          <p className="text-[10px] text-[#3B2D5E]">{s.changeOverHistory}</p>
          <div className="mt-2"><Sparkline points={ownHistory} color="#3D1D6E" /></div>
        </article>
      </div>
      <div className="mt-3 rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
        <p className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{s.sentimentByBusiness}</p>
        <div className="mt-2 space-y-2">
          {mixRows.map((x) => {
            const pos = x.facts.positive_pct ?? 0; const neg = x.facts.negative_pct ?? 0; const neu = Math.max(0, 100 - pos - neg); const has = x.facts.positive_pct != null || x.facts.negative_pct != null;
            return (
              <div key={x.key} className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)_auto] items-center gap-2">
                <span className={`truncate text-[10px] ${x.key === own.key ? "font-bold text-[#14101F]" : "text-[#3B2D5E]"}`} title={x.name ?? undefined}>{x.name || "—"}</span>
                <div className="flex h-2.5 overflow-hidden rounded-full bg-[#F1F2F5]" aria-hidden>{has ? <><div className="bg-[#116631]" style={{ width: `${pos}%` }} /><div className="bg-[#D8D8DC]" style={{ width: `${neu}%` }} /><div className="bg-[#B3123A]" style={{ width: `${neg}%` }} /></> : null}</div>
                <span className="font-mono text-[10px] text-[#3B2D5E]">{has ? `${Math.round(pos)}%` : "—"}</span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}