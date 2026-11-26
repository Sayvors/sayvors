"use client";

import { useMemo } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject, HistoryPoint, SubjectReviews, ReviewThemesResponse } from "@/lib/api-benchmark";

type Props = {
  subjects: ComparisonSubject[];
  mainKey?: string | null;
  reviewSubjects: SubjectReviews[];
  historyBySubject: Record<string, HistoryPoint[]>;
  themes?: ReviewThemesResponse | null;
};

const COLORS = ["#3D1D6E", "#FF4F6E", "#116631", "#B0338A", "#8A6100", "#2B6CB0"];
const GOOD = "#116631";
const BAD = "#B3123A";
const MID = "#D8D8DC";
const OWN = "#3D1D6E";

function n(v: unknown): number | null { return typeof v === "number" && Number.isFinite(v) ? v : null; }
function pct(v: number, total: number) { return total > 0 ? (v / total) * 100 : 0; }
function short(name: string | null | undefined, max = 14) { const s = (name || "—").trim(); return s.length > max ? s.slice(0, max - 1) + "…" : s; }

function InfoTip({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex">
      <button type="button" aria-label={text} className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-[var(--ui-line)] bg-white text-[9px] font-bold text-[#3B2D5E] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]">i</button>
      <span role="tooltip" className="pointer-events-none absolute right-0 top-5 z-20 hidden w-56 rounded-[8px] border border-[var(--ui-line)] bg-white px-2.5 py-2 text-[10px] leading-relaxed text-[#3B2D5E] shadow-[0_8px_20px_rgba(20,16,31,0.08)] group-hover:block group-focus-within:block">{text}</span>
    </span>
  );
}

function Card({ title, subtitle, info, children }: { title: string; subtitle?: string; info: string; children: React.ReactNode }) {
  return (
    <article className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-[11px] font-bold uppercase tracking-wide text-[#14101F]">{title}</h3>
          {subtitle ? <p className="mt-0.5 text-[10px] text-[#3B2D5E]">{subtitle}</p> : null}
        </div>
        <InfoTip text={info} />
      </div>
      <div className="mt-2">{children}</div>
    </article>
  );
}

function HBar({ rows, max, fmt }: { rows: Array<{ label: string; value: number | null; color: string; own?: boolean }>; max?: number; fmt: (v: number) => string }) {
  const m = max ?? Math.max(...rows.map((r) => r.value ?? 0), 1);
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[minmax(0,92px)_minmax(0,1fr)_auto] items-center gap-2">
          <span className={`truncate text-[10px] ${r.own ? "font-bold text-[#14101F]" : "text-[#3B2D5E]"}`} title={r.label}>{r.label}</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-[#F1F2F5]"><div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, ((r.value ?? 0) / Math.max(m, 0.0001)) * 100))}%`, backgroundColor: r.color }} /></div>
          <span className="font-mono text-[10px] text-[#3B2D5E]">{r.value == null ? "—" : fmt(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

function Donut({ parts, size = 120 }: { parts: Array<{ label: string; value: number; color: string }>; size?: number }) {
  const total = parts.reduce((s, p) => s + Math.max(0, p.value), 0);
  const r = size / 2 - 8; const c = 2 * Math.PI * r; let off = 0;
  return (
    <div className="flex items-center gap-3">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="donut chart">
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#F1F2F5" strokeWidth="14" />
          {total > 0 && parts.map((p) => { const v = Math.max(0, p.value); const dash = (v / total) * c; const seg = <circle key={p.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.color} strokeWidth="14" strokeDasharray={`${dash} ${c - dash}`} strokeDashoffset={-off} />; off += dash; return seg; })}
        </g>
        <text x={size / 2} y={size / 2 + 4} textAnchor="middle" fontSize="12" fontWeight="700" fill="#14101F">{total || "—"}</text>
      </svg>
      <div className="space-y-1 text-[10px] text-[#3B2D5E]">
        {parts.map((p) => (<div key={p.label} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} /><span>{p.label} {total > 0 ? Math.round(pct(p.value, total)) : 0}%</span></div>))}
      </div>
    </div>
  );
}

function LineChart({ series, height = 140, empty }: { series: Array<{ label: string; color: string; points: Array<{ x: string; y: number | null }> }>; height?: number; empty: string }) {
  const W = 320; const H = height; const pad = 24;
  const allY = series.flatMap((s) => s.points.map((p) => p.y).filter((v): v is number => v != null));
  if (allY.length < 2) return <div className="text-[10px] text-[#8A8496]">{empty}</div>;
  const minY = Math.min(...allY); const maxY = Math.max(...allY); const span = Math.max(maxY - minY, 0.0001);
  const xCount = Math.max(...series.map((s) => s.points.length), 2);
  const sx = (i: number) => pad + (i / Math.max(xCount - 1, 1)) * (W - pad * 2);
  const sy = (v: number) => H - pad - ((v - minY) / span) * (H - pad * 2);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="line chart">
      {[0, 0.5, 1].map((t) => { const y = pad + t * (H - pad * 2); return <line key={t} x1={pad} x2={W - pad} y1={y} y2={y} stroke="rgba(20,16,31,0.08)" />; })}
      {series.map((s) => { const pts = s.points.map((p, i) => p.y == null ? null : `${sx(i)},${sy(p.y)}`).filter(Boolean) as string[]; if (pts.length < 2) return null; return <polyline key={s.label} fill="none" stroke={s.color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" points={pts.join(" ")} />; })}
      {series.map((s) => (<text key={s.label} x={pad} y={12 + series.indexOf(s) * 10} fontSize="8" fill={s.color}>{short(s.label, 18)}</text>))}
    </svg>
  );
}

export default function BenchmarkChartsGallery({ subjects, mainKey, reviewSubjects, historyBySubject, themes }: Props) {
  const { t } = useI18n();
  const c = t.benchmark.charts;
  const available = subjects.filter((s) => s.available);
  const own = available.find((s) => s.key === mainKey) ?? available.find((s) => s.kind === "own");
  const reviewMap = useMemo(() => Object.fromEntries(reviewSubjects.map((r) => [r.key, r])), [reviewSubjects]);
  if (available.length < 2) return null;

  const ratingRows = available.map((s, i) => ({ label: short(s.name), value: n(s.metrics.avg_rating), color: s.key === own?.key ? OWN : COLORS[i % COLORS.length], own: s.key === own?.key }));
  const volumeRows = available.map((s, i) => ({ label: short(s.name), value: n(s.metrics.total_reviews), color: s.key === own?.key ? OWN : COLORS[i % COLORS.length], own: s.key === own?.key }));
  const velocityRows = available.map((s, i) => ({ label: short(s.name), value: n(s.metrics.reviews_last_month) ?? (n(s.metrics.reviews_last_year) != null ? (n(s.metrics.reviews_last_year)! / 12) : null), color: s.key === own?.key ? OWN : COLORS[i % COLORS.length], own: s.key === own?.key }));
  const responseRows = available.map((s, i) => ({ label: short(s.name), value: n(reviewMap[s.key]?.summary.response_rate), color: s.key === own?.key ? OWN : COLORS[i % COLORS.length], own: s.key === own?.key }));
  const leaderRating = Math.max(...available.map((s) => n(s.metrics.avg_rating) ?? 0), 0);
  const gapRows = available.map((s, i) => { const r = n(s.metrics.avg_rating); return { label: short(s.name), value: r == null ? null : Math.max(0, leaderRating - r), color: s.key === own?.key ? BAD : COLORS[i % COLORS.length], own: s.key === own?.key }; });
  const ownSent = own ? [
    { label: c.positive, value: n(own.facts.positive_pct) ?? 0, color: GOOD },
    { label: c.neutral, value: Math.max(0, 100 - (n(own.facts.positive_pct) ?? 0) - (n(own.facts.negative_pct) ?? 0)), color: MID },
    { label: c.negative, value: n(own.facts.negative_pct) ?? 0, color: BAD },
  ] : [];
  const shareParts = available.map((s, i) => ({ label: short(s.name), value: n(s.metrics.total_reviews) ?? 0, color: s.key === own?.key ? OWN : COLORS[i % COLORS.length] }));
  const ratingHistorySeries = available.slice(0, 4).map((s, i) => ({ label: s.name || s.key, color: s.key === own?.key ? OWN : COLORS[i % COLORS.length], points: (historyBySubject[s.key] ?? []).map((p) => ({ x: p.at ?? "", y: n(p.rating) })) }));
  const reviewHistorySeries = available.slice(0, 4).map((s, i) => ({ label: s.name || s.key, color: s.key === own?.key ? OWN : COLORS[i % COLORS.length], points: (historyBySubject[s.key] ?? []).map((p) => ({ x: p.at ?? "", y: n(p.reviews) })) }));
  const scatterPoints = available.map((s, i) => ({ s, x: n(s.metrics.total_reviews), y: n(s.metrics.avg_rating), c: s.key === own?.key ? OWN : COLORS[i % COLORS.length] })).filter((p): p is { s: ComparisonSubject; x: number; y: number; c: string } => p.x != null && p.y != null);
  const scatterW = 320; const scatterH = 160; const sp = 24; const sxMax = Math.max(...scatterPoints.map((p) => p.x), 1); const syMin = Math.max(1, Math.min(...scatterPoints.map((p) => p.y)) - 0.2);
  const sx = (v: number) => sp + (v / sxMax) * (scatterW - sp * 2); const sy = (v: number) => scatterH - sp - ((v - syMin) / Math.max(5 - syMin, 0.0001)) * (scatterH - sp * 2);
  const complaintRows = (themes?.rows ?? []).filter((r) => r.sentiment === "negative").slice(0, 5).map((r) => ({ label: short(r.label, 20), value: r.own_pct ?? r.cells[own?.key ?? ""]?.percentage ?? null, color: BAD }));

  return (
    <section aria-labelledby="charts-gallery-title" className="mt-6">
      <h2 id="charts-gallery-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{c.sectionTitle}</h2>
      <p className="mt-0.5 text-[11px] text-[#3B2D5E]">{c.sectionDesc}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <Card title={c.ratingComparison} subtitle={c.ratingComparisonDesc} info={c.ratingComparisonInfo}><HBar rows={ratingRows} max={5} fmt={(v) => v.toFixed(1)} /></Card>
        <Card title={c.reviewVolume} subtitle={c.reviewVolumeDesc} info={c.reviewVolumeInfo}><HBar rows={volumeRows} fmt={(v) => Math.round(v).toString()} /></Card>
        <Card title={c.reviewVelocity} subtitle={c.reviewVelocityDesc} info={c.reviewVelocityInfo}><HBar rows={velocityRows} fmt={(v) => v.toFixed(1)} /></Card>
        <Card title={c.responseRate} subtitle={c.responseRateDesc} info={c.responseRateInfo}><HBar rows={responseRows} max={100} fmt={(v) => `${Math.round(v)}%`} /></Card>
        <Card title={c.gapToLeader} subtitle={c.gapToLeaderDesc} info={c.gapToLeaderInfo}><HBar rows={gapRows} fmt={(v) => v.toFixed(2)} /></Card>
        <Card title={c.marketShare} subtitle={c.marketShareDesc} info={c.marketShareInfo}><Donut parts={shareParts} /></Card>
        <Card title={c.sentimentMix} subtitle={own?.name ? c.sentimentMixDesc(short(own.name, 24)) : undefined} info={c.sentimentMixInfo}>{ownSent.length ? <Donut parts={ownSent} /> : <p className="text-[10px] text-[#8A8496]">{c.noSentiment}</p>}</Card>
        <Card title={c.ratingTrend} subtitle={c.ratingTrendDesc} info={c.ratingTrendInfo}><LineChart series={ratingHistorySeries} empty={c.noHistory} /></Card>
        <Card title={c.reviewGrowth} subtitle={c.reviewGrowthDesc} info={c.reviewGrowthInfo}><LineChart series={reviewHistorySeries} empty={c.noHistory} /></Card>
        <Card title={c.ratingVsVolume} subtitle={c.ratingVsVolumeDesc} info={c.ratingVsVolumeInfo}>
          {scatterPoints.length > 1 ? (
            <svg viewBox={`0 0 ${scatterW} ${scatterH}`} className="h-auto w-full" role="img" aria-label={c.ratingVsVolume}>
              <rect x={sp} y={10} width={scatterW - sp * 2} height={scatterH - sp - 10} fill="#FAFAFB" stroke="rgba(20,16,31,0.08)" />
              {scatterPoints.map((p) => (<g key={p.s.key}><circle cx={sx(p.x)} cy={sy(p.y)} r={p.s.key === own?.key ? 6 : 5} fill={p.c} fillOpacity={0.85} /><title>{`${p.s.name || "—"}: ${p.y.toFixed(1)}★, ${p.x}`}</title></g>))}
              <text x={scatterW / 2} y={scatterH - 6} textAnchor="middle" fontSize="9" fill="#3B2D5E">{c.totalReviews}</text>
              <text x={10} y={scatterH / 2} textAnchor="middle" fontSize="9" fill="#3B2D5E" transform={`rotate(-90 10 ${scatterH / 2})`}>{c.rating}</text>
            </svg>
          ) : <p className="text-[10px] text-[#8A8496]">{c.noData}</p>}
        </Card>
        <Card title={c.fiveVsOne} subtitle={c.fiveVsOneDesc} info={c.fiveVsOneInfo}>
          <div className="space-y-1.5">
            {available.slice(0, 6).map((s) => {
              const five = n(s.metrics.five_star) ?? 0; const one = n(s.metrics.one_star) ?? 0; const total = Math.max(five + one, 1);
              return (
                <div key={s.key} className="grid grid-cols-[minmax(0,92px)_minmax(0,1fr)_auto] items-center gap-2">
                  <span className={`truncate text-[10px] ${s.key === own?.key ? "font-bold text-[#14101F]" : "text-[#3B2D5E]"}`}>{short(s.name)}</span>
                  <div className="flex h-2.5 overflow-hidden rounded-full bg-[#F1F2F5]"><div className="bg-[#116631]" style={{ width: `${pct(five, total)}%` }} /><div className="bg-[#B3123A]" style={{ width: `${pct(one, total)}%` }} /></div>
                  <span className="font-mono text-[10px] text-[#3B2D5E]">{five}/{one}</span>
                </div>
              );
            })}
          </div>
        </Card>
        <Card title={c.topComplaints} subtitle={c.topComplaintsDesc} info={c.topComplaintsInfo}>
          {complaintRows.length ? <HBar rows={complaintRows.map((r) => ({ ...r, own: false }))} max={100} fmt={(v) => `${Math.round(v)}%`} /> : <p className="text-[10px] text-[#8A8496]">{c.noThemes}</p>}
        </Card>
      </div>
    </section>
  );
}