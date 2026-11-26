"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";

function velocity(s: ComparisonSubject): number | null {
  if (typeof s.metrics.reviews_last_month === "number") return s.metrics.reviews_last_month;
  if (typeof s.metrics.reviews_last_year === "number") return s.metrics.reviews_last_year / 12;
  return null;
}

export default function MarketPositionScatter({ subjects, mainKey }: { subjects: ComparisonSubject[]; mainKey?: string | null }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const m = b.market;
  const points = subjects
    .filter((s) => s.available && typeof s.metrics.avg_rating === "number" && s.metrics.avg_rating > 0)
    .map((s) => ({ s, x: velocity(s), y: s.metrics.avg_rating as number, r: s.metrics.total_reviews ?? s.metrics.total_ratings ?? 0 }))
    .filter((p): p is { s: ComparisonSubject; x: number; y: number; r: number } => typeof p.x === "number");

  if (points.length < 2) return null;
  const W = 360, H = 170, pad = 28;
  const maxX = Math.max(...points.map((p) => p.x), 1);
  const minY = Math.max(3.2, Math.floor(Math.min(...points.map((p) => p.y)) * 10) / 10 - 0.2);
  const maxY = 5;
  const maxR = Math.max(...points.map((p) => p.r), 1);
  const sx = (v: number) => pad + (v / Math.max(maxX, 0.0001)) * (W - pad * 2);
  const sy = (v: number) => H - pad - ((v - minY) / Math.max(maxY - minY, 0.0001)) * (H - pad * 2);
  const midX = sx(maxX / 2);
  const midY = sy(minY + (maxY - minY) / 2);

  return (
    <section aria-labelledby="market-position-title" className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 id="market-position-title" className="text-[11px] font-bold uppercase tracking-wide text-[#14101F]">{b.marketPosition || "Market position"}</h2>
          <p className="mt-0.5 text-[10px] text-[#3B2D5E]">{m.desc}</p>
        </div>
        <div className="flex gap-2 text-[9px] font-semibold text-[#3B2D5E]">
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#3D1D6E]" />{m.you}</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#FF4F6E]" />{m.peers}</span>
        </div>
      </div>
      <div className="mt-2 grid gap-3 sm:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full max-w-[360px]" role="img" aria-label={b.marketPosition || "Market position"}>
          <rect x={pad} y={10} width={W - pad * 2} height={H - pad - 10} rx="8" fill="#FAFAFB" stroke="rgba(20,16,31,0.08)" />
          <line x1={midX} x2={midX} y1={10} y2={H - pad} stroke="rgba(20,16,31,0.08)" />
          <line x1={pad} x2={W - pad} y1={midY} y2={midY} stroke="rgba(20,16,31,0.08)" />
          <text x={W - pad - 4} y={18} textAnchor="end" fontSize="8" fill="#116631">{m.strong}</text>
          <text x={pad + 4} y={H - pad - 4} fontSize="8" fill="#8A6100">{m.watch}</text>
          {points.map((p) => {
            const own = p.s.key === mainKey;
            const radius = 4 + Math.sqrt(p.r / maxR) * 6;
            return (
              <g key={p.s.key}>
                <circle cx={sx(p.x)} cy={sy(p.y)} r={radius} fill={own ? "#3D1D6E" : "#FF4F6E"} fillOpacity={own ? 0.95 : 0.7} stroke="white" strokeWidth="1.5" />
                <title>{`${p.s.name || "—"}: ${p.y.toFixed(1)}★, ${p.x.toFixed(1)}/mo`}</title>
              </g>
            );
          })}
          <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="9" fill="#3B2D5E">{m.velocityPerMonth}</text>
          <text x={10} y={H / 2} textAnchor="middle" fontSize="9" fill="#3B2D5E" transform={`rotate(-90 10 ${H / 2})`}>{m.rating}</text>
        </svg>
        <div className="grid grid-cols-2 gap-2 content-start">
          {points.slice().sort((a, c) => (c.s.key === mainKey ? 1 : 0) - (a.s.key === mainKey ? 1 : 0) || c.y - a.y).slice(0, 4).map((p) => {
            const own = p.s.key === mainKey;
            return (
              <div key={p.s.key} className="rounded-[8px] border border-[var(--ui-line)] bg-[#FAFAFB] px-2 py-1.5">
                <div className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${own ? "bg-[#3D1D6E]" : "bg-[#FF4F6E]"}`} /><span className="truncate text-[10px] font-semibold text-[#14101F]" title={p.s.name ?? undefined}>{p.s.name || "—"}</span></div>
                <p className="mt-0.5 text-[10px] text-[#3B2D5E]">{p.y.toFixed(1)}★ · {p.x.toFixed(1)}/mo</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}