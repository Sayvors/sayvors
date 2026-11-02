"use client";

import InsightsPanel from "@/components/analytics/InsightsPanel";
import { useI18n } from "@/lib/i18n/I18nProvider";

/* Standalone route for the Insights tab. The analytics shell embeds
 * InsightsPanel directly, so it does not inherit this page header or the
 * outer scroll container. */
export default function InsightsPage() {
  const { t } = useI18n();
  const copy = t.analytics.insights;

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <header className="mb-5">
        <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">
          {copy.title}
        </h1>
        <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">
          {copy.subtitle}
        </p>
      </header>
      <InsightsPanel />
    </div>
  );
}
