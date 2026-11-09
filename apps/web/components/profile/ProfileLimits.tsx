"use client";

import type { UsageItem } from "@/lib/api-profile";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type ProfileDict = Dict["profile"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

// Solid fills only — one colour per row, cycled. No gradients.
const BAR = ["bg-deep-violet", "bg-magenta", "bg-sky-500", "bg-emerald-500"];

const CARD =
  "rounded-[32px] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)] ring-1 ring-ink/[0.06] dark:bg-[#1b1530] dark:ring-white/[0.08] sm:p-7";

export default function ProfileLimits({
  items,
  cached,
  loading,
  onRefresh,
}: {
  items: UsageItem[];
  cached: boolean;
  loading: boolean;
  onRefresh: () => void;
}) {
  const { t, locale } = useI18n();
  const pf: ProfileDict = t.profile;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  return (
    <section aria-labelledby="usage-title" className={CARD}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 id="usage-title" className="text-[17px] font-black tracking-tight text-ink dark:text-fog">
            {pf.usageTitle}
          </h2>
          <p className="mt-0.5 text-[11.5px] text-ink/50 dark:text-fog/50">
            {fill(pf.usageSub, { cached: cached ? pf.cachedSuffix : "" })}
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="rounded-[20px] border border-ink/[0.12] px-3.5 py-2 text-[11.5px] font-bold text-ink/65 transition hover:border-deep-violet/40 hover:text-deep-violet focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 active:translate-y-0.5 active:scale-[0.98] disabled:opacity-50 dark:border-white/[0.12] dark:text-fog/65"
        >
          {loading ? pf.usageRefreshing : pf.usageRefresh}
        </button>
      </div>

      {loading && items.length === 0 ? (
        <div className="space-y-4" aria-label={pf.usageLoading}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-[16px] bg-ink/[0.05] dark:bg-white/[0.05]" />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item, i) => {
            const percent = Math.max(0, Math.min(item.percent, 100));
            return (
              <div key={item.label}>
                <div className="mb-1.5 flex items-baseline justify-between gap-2">
                  <span className="text-[12px] font-bold text-ink dark:text-fog">{item.label}</span>
                  <span className="text-[10.5px] tabular-nums text-ink/45 dark:text-fog/45">
                    {fmt(item.used)} / {fmt(item.total)} {item.unit}
                  </span>
                </div>
                <div
                  className="h-2 w-full overflow-hidden rounded-full bg-ink/[0.07] dark:bg-white/[0.09]"
                  role="progressbar"
                  aria-valuenow={Math.round(item.percent)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuetext={fill(pf.percentUsed, { n: fmt(Math.round(item.percent)) })}
                  aria-label={fill(pf.usageAria, { label: item.label })}
                >
                  <div
                    className={`h-full rounded-full transition-[width] duration-500 ${BAR[i % BAR.length]}`}
                    style={{ width: `${percent}%` }}
                  />
                </div>
                <p className="mt-1 text-[10px] tabular-nums text-ink/35 dark:text-fog/35">
                  {fill(pf.percentUsed, { n: fmt(Math.round(item.percent)) })}
                </p>
              </div>
            );
          })}
          {items.length === 0 && !loading && (
            <p className="text-[12px] text-ink/45 dark:text-fog/45">{pf.usageEmpty}</p>
          )}
        </div>
      )}
    </section>
  );
}
