"use client";

/**
 * Baseline alert for the own subject's rating: fires only when the history
 * is long enough AND the latest reading has moved ≥0.15 off the baseline
 * (the math lives in lib/benchmark-insights). Amber banner, arrow + streak,
 * so a drift that has settled in gets named while it is still recent.
 */
import { useI18n } from "@/lib/i18n/I18nProvider";
import { baselineDeviation } from "@/lib/benchmark-insights";
import type { HistoryPoint } from "@/lib/api-benchmark";

export default function BaselineAlert({ points }: { points: HistoryPoint[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const deviation = baselineDeviation(points);
  if (!deviation.hasEnough || deviation.direction == null) return null;
  const delta = Math.abs(deviation.delta).toFixed(2);
  return (
    <div
      role="status"
      className="mt-4 flex items-start gap-2 rounded-[8px] border border-[#8A6100]/30 bg-[#FFF3D6] px-3 py-2"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className="mt-0.5 shrink-0"
        style={{ transform: deviation.direction === "down" ? "rotate(180deg)" : undefined }}
      >
        <path d="M12 4 3 18h18L12 4z" fill="#8A6100" />
      </svg>
      <p className="text-[11px] leading-relaxed text-[#8A6100]">
        {(deviation.direction === "up" ? b.baselineUp : b.baselineDown)
          .replace("{delta}", delta)
          .replace("{streak}", String(deviation.streak))}
      </p>
    </div>
  );
}
