"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useI18n } from "@/lib/i18n/I18nProvider";
import OverviewPanel from "@/components/analytics/OverviewPanel";
import BenchmarkPage from "../benchmark/page";
import InsightsPage from "../insights/page";
import GrowthPage from "../growth/page";

/* Analytics shell: header, tab bar, tab switch. The tab panels live in
 * components/analytics/ (OverviewPanel) and their own route files.
 *
 * Theme: the Team page's flat system. This root carries `.team-ui` — the
 * class that DEFINES the --ui-* variables and paints the #F5F5F5 page —
 * so every panel rendered below it can consume the vars. Three colours
 * only: ink, surface, sunken; depth from hairlines, never shadows. */

const TABS = ["overview", "insights", "growth", "benchmark"] as const;

type AnalyticsTab = (typeof TABS)[number];

function AnalyticsShell() {
  const { t } = useI18n();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: AnalyticsTab =
    raw === "insights" || raw === "growth" || raw === "benchmark" ? raw : "overview";

  return (
    <div className="team-ui flex h-full flex-col">
      <div className="shrink-0 px-4 pt-4 sm:px-6 sm:pt-6">
        <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">{t.nav.analytics}</h1>
        <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">
          {t.analytics.subtitle}
        </p>
        <div
          role="tablist"
          aria-label={t.analytics.sections}
          className="mt-4 flex gap-1 overflow-x-auto rounded-[2px] bg-[var(--ui-sunken)] p-1"
        >
          {TABS.map((tabId) => {
            const active = tab === tabId;
            const label = tabId === "overview"
              ? t.analytics.overview
                : t.nav[tabId];
            return (
              <Link
                key={tabId}
                role="tab"
                aria-selected={active}
                href={tabId === "overview" ? "/dashboard/analytics" : `/dashboard/analytics?tab=${tabId}`}
                scroll={false}
                className={`whitespace-nowrap rounded-[2px] px-3.5 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                  active
                    ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                    : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </div>
      </div>
      <div className="mt-3 min-h-0 flex-1">
        {tab === "overview" && <OverviewPanel />}
        {tab === "insights" && <InsightsPage />}
        {tab === "growth" && <GrowthPage />}
        {tab === "benchmark" && <BenchmarkPage />}
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense>
      <AnalyticsShell />
    </Suspense>
  );
}
