"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api-rag";
import { fetchOverview, fetchTimeseries, type Overview, type TimeseriesPoint } from "@/lib/api-analytics";
import { useI18n } from "@/lib/i18n/I18nProvider";
import Greeting from "@/components/dashboard/Greeting";
import { MetricChart, RatingDistribution } from "@/components/analytics/Charts";

interface ExecSummary {
  headline: string;
  reputation_score: number;
  health_score: number;
  wins: string[];
  problems: string[];
  opportunity: string;
  recommended_action: string;
  benchmark_text: string;
}

const quickActions = [
  {
    titleKey: "connectTitle",
    descKey: "connectDesc",
    href: "/dashboard/channels",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
      </svg>
    ),
    color: "from-deep-violet to-magenta",
  },
  {
    titleKey: "databankTitle",
    descKey: "databankDesc",
    href: "/dashboard/databank",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    ),
    color: "from-magenta to-coral",
  },
  {
    titleKey: "autoReplyTitle",
    descKey: "autoReplyDesc",
    href: "/dashboard/automations",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        <path d="M8 10h8M8 14h4" />
      </svg>
    ),
    color: "from-sky-400 to-blue-500",
  },
] as const;

const statDefs = [
  { labelKey: "messages", subKey: "messagesSub", value: "0" },
  { labelKey: "channels", subKey: "channelsSub", value: "0" },
  { labelKey: "reviews", subKey: "reviewsSub", value: "0" },
  { labelKey: "responseTime", subKey: "responseTimeSub", value: "--" },
] as const;

const checklistDefs = [
  { id: "channel", labelKey: "stepConnect", href: "/dashboard/channels" },
  { id: "databank", labelKey: "stepDatabank", href: "/dashboard/databank" },
  { id: "auto-reply", labelKey: "stepAutoReply", href: "/dashboard/automations" },
] as const;

const CHECKLIST_KEY = "sayvors.onboarding.checklist";

function ExecutiveSummaryBanner() {
  const { t } = useI18n();
  const [summary, setSummary] = useState<ExecSummary | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/analytics/executive-summary?days=30")
      .then((s) => {
        if (!cancelled) setSummary(s);
      })
      .catch(() => {
        /* banner stays hidden when no data / backend down */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!summary) return null;
  return (
    <section
      aria-label={t.dashboard.briefing.title}
      className="relative overflow-hidden rounded-2xl border-2 border-white bg-gradient-to-r from-deep-violet to-magenta p-5 text-white shadow-md shadow-deep-violet/20"
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-white/15">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5" aria-hidden>
            <path d="M12 2a7 7 0 014 12.7V17a1 1 0 01-1 1H9a1 1 0 01-1-1v-2.3A7 7 0 0112 2z" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M9 21h6" strokeLinecap="round" />
          </svg>
        </span>
        <h2 className="text-[13px] font-bold tracking-wide">{t.dashboard.briefing.title}</h2>
        <span className="ml-auto flex items-center gap-3 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold">
          <span title={t.dashboard.briefing.reputation}>{t.dashboard.briefing.reputation} {summary.reputation_score}</span>
          <span className="h-3 w-px bg-white/25" aria-hidden />
          <span title={t.dashboard.briefing.health}>{t.dashboard.briefing.health} {summary.health_score}</span>
        </span>
      </div>
      <p className="text-[13px] font-semibold leading-snug">{summary.headline}</p>
      <ul className="mt-2 grid gap-1 sm:grid-cols-2">
        {summary.wins.slice(0, 2).map((w) => (
          <li key={w} className="flex items-center gap-2 text-[12px] text-white/90">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald" aria-hidden />
            {w}
          </li>
        ))}
        {summary.problems.slice(0, 1).map((p) => (
          <li key={p} className="flex items-center gap-2 text-[12px] text-white/90 sm:col-start-1">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
            {p}
          </li>
        ))}
        {summary.opportunity && (
          <li className="flex items-center gap-2 text-[12px] text-white/90">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky" aria-hidden />
            {summary.opportunity}
          </li>
        )}
      </ul>
      <p className="mt-2.5 border-t border-white/15 pt-2 text-[11px] text-white/75">
        <span className="font-semibold">{t.dashboard.briefing.recommendedAction}</span> {summary.recommended_action} · {summary.benchmark_text}
      </p>
    </section>
  );
}

type DashboardChannel = { id: string; platform: string; display_name: string | null };
type DashboardService = { is_offered: boolean };

function BusinessPulse() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [points, setPoints] = useState<TimeseriesPoint[]>([]);
  const [channels, setChannels] = useState<DashboardChannel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [serviceCount, setServiceCount] = useState(0);
  const [offeredCount, setOfferedCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function loadPulse() {
      try {
        const channelData = await apiFetch("/api/v1/channels/?limit=100");
        const googleChannels = (channelData.channels ?? []).filter(
          (channel: DashboardChannel) => channel.platform === "google_reviews"
        );
        const [nextOverview, nextPoints, serviceResults] = await Promise.all([
          fetchOverview(30, channelId || null),
          fetchTimeseries(30, channelId || null),
          Promise.all((channelId ? googleChannels.filter((channel: DashboardChannel) => channel.id === channelId) : googleChannels).map((channel: DashboardChannel) => apiFetch(`/api/v1/channels/${channel.id}/services`))),
        ]);
        if (cancelled) return;
        const allServices = serviceResults.flatMap((result) => (result.services ?? []) as DashboardService[]);
        setChannels(googleChannels);
        setOverview(nextOverview);
        setPoints(nextPoints);
        setServiceCount(allServices.length);
        setOfferedCount(allServices.filter((service) => service.is_offered).length);
      } catch {
        if (!cancelled) {
          setOverview(null);
          setPoints([]);
          setChannels([]);
          setServiceCount(0);
          setOfferedCount(0);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadPulse();
    return () => {
      cancelled = true;
    };
  }, [channelId]);

  const totalReviews = overview?.total_reviews ?? 0;
  const ratingDistribution = overview?.rating_distribution ?? {};

  return (
    <section aria-label="Business pulse" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[16px] font-bold text-ink">Business pulse</h2>
          <p className="mt-0.5 text-[12px] text-ink/50">A quick view of your connected businesses and customer activity.</p>
        </div>
        <div className="flex items-center gap-2">
          {channels.length > 0 && <select value={channelId} onChange={(event) => { setLoading(true); setChannelId(event.target.value); }} aria-label="Business scope" className="rounded-lg border border-ink/[0.08] bg-white px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 outline-none focus:border-deep-violet/30"><option value="">All businesses</option>{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed business"}</option>)}</select>}
          <span className="text-[11px] font-semibold text-ink/40">Last 30 days</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <PulseStat label="Total reviews" value={totalReviews} detail={overview ? `${overview.avg_rating.toFixed(1)} average rating` : "No review data yet"} color="text-amber-600" />
        <PulseStat label="Connected businesses" value={channels.length} detail={channels.length ? "Google Business channels" : "No Google channel yet"} color="text-deep-violet" />
        <PulseStat label="Services offered" value={offeredCount} detail={serviceCount ? `${serviceCount} services configured` : "No service data yet"} color="text-emerald-600" />
        <PulseStat label="Working hours" value="--" detail="Not configured yet" color="text-sky-600" />
      </div>

      <div className="grid gap-3 lg:grid-cols-[1.7fr_1fr]">
        {loading ? <div className="h-72 animate-pulse rounded-2xl border-2 border-white bg-white/60" /> : <MetricChart points={points} />}
        <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-4 text-[14px] font-bold text-ink">Review ratings</h3>
          <RatingDistribution distribution={ratingDistribution} total={totalReviews} />
          <div className="mt-5 border-t border-ink/[0.06] pt-4">
            <div className="flex items-center justify-between text-[11px] text-ink/45"><span>Response rate</span><strong className="text-ink">{overview ? `${Math.round(overview.response_rate)}%` : "--"}</strong></div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/[0.06]"><div className="h-full rounded-full bg-emerald" style={{ width: `${Math.min(100, overview?.response_rate ?? 0)}%` }} /></div>
          </div>
        </div>
      </div>
    </section>
  );
}

function PulseStat({ label, value, detail, color }: { label: string; value: number | string; detail: string; color: string }) {
  return <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm"><p className="text-[10px] font-semibold uppercase tracking-wide text-ink/50">{label}</p><p className={`mt-1 text-[22px] font-bold ${color}`}>{value}</p><p className="truncate text-[10px] text-ink/40">{detail}</p></div>;
}

const EMPTY_CHECKLIST: Record<string, boolean> = {};
let cachedRaw: string | null = null;
let cachedValue: Record<string, boolean> = EMPTY_CHECKLIST;

function readChecklist(): Record<string, boolean> {
  if (typeof window === "undefined") return EMPTY_CHECKLIST;
  const raw = window.localStorage.getItem(CHECKLIST_KEY);
  if (raw === cachedRaw) return cachedValue;
  if (raw === null) {
    cachedValue = EMPTY_CHECKLIST;
  } else {
    try {
      cachedValue = JSON.parse(raw) ?? EMPTY_CHECKLIST;
    } catch {
      cachedValue = EMPTY_CHECKLIST;
    }
  }
  cachedRaw = raw;
  return cachedValue;
}

const checklistListeners = new Set<() => void>();

function subscribeChecklist(callback: () => void) {
  checklistListeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    checklistListeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

function getServerChecklist(): Record<string, boolean> {
  return EMPTY_CHECKLIST;
}

function writeChecklist(next: Record<string, boolean>) {
  try {
    window.localStorage.setItem(CHECKLIST_KEY, JSON.stringify(next));
  } catch {
    // storage unavailable — updates still broadcast for this session
  }
  checklistListeners.forEach((listener) => listener());
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { dir, t } = useI18n();
  const done = useSyncExternalStore(subscribeChecklist, readChecklist, getServerChecklist);

  const checklistItems = checklistDefs.map((d) => ({
    ...d,
    label: t.dashboard.start[d.labelKey],
  }));

  const toggleItem = useCallback((id: string) => {
    const current = readChecklist();
    writeChecklist({ ...current, [id]: !current[id] });
  }, []);

  const completed = checklistItems.filter((i) => done[i.id]).length;
  const total = checklistItems.length;
  const progress = total === 0 ? 0 : Math.round((completed / total) * 100);
  const allDone = completed === total;
  const nextItem = checklistItems.find((i) => !done[i.id]) ?? null;
  const [dismissed, setDismissed] = useState(() => {
    try {
      return typeof window !== "undefined" && window.localStorage.getItem("sayvors.onboarding.checklist.dismissed") === "1";
    } catch {
      return false;
    }
  });
  const dismissChecklist = useCallback(() => {
    try {
      window.localStorage.setItem("sayvors.onboarding.checklist.dismissed", "1");
    } catch {
      /* storage unavailable */
    }
    setDismissed(true);
  }, []);
  const showChecklist = !allDone || !dismissed;
  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-5 bg-[#f3f0ff]">
      {/* AI Executive Summary */}
      <ExecutiveSummaryBanner />

      {/* Header */}
      <div>
        <Greeting name={user?.first_name ?? t.dashboard.greetingFallback} />
        <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">
          {t.dashboard.subtitle}
        </p>
      </div>

      {/* Getting Started checklist — first thing a new user must see */}
      {showChecklist && (
        <section
          aria-label={t.dashboard.start.title}
          className="relative overflow-hidden rounded-2xl bg-white p-5 shadow-md shadow-deep-violet/[0.08] ring-2 ring-deep-violet/30"
        >
          <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-deep-violet via-magenta to-coral" />
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
                <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z" />
                <path d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 01-4 2z" />
                <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
                <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
              </svg>
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[15px] font-bold text-ink">{t.dashboard.start.title}</h2>
                <span className="rounded-full bg-deep-violet/[0.08] px-2.5 py-0.5 text-[11px] font-bold tabular-nums text-deep-violet">
                  {allDone ? t.dashboard.start.allSet : t.dashboard.start.doneOf.replace("{done}", String(completed)).replace("{total}", String(total))}
                </span>
              </div>
              <p className="mt-0.5 text-[12px] text-ink/55">
                {allDone
                  ? t.dashboard.start.subtitleDone
                  : t.dashboard.start.subtitleTodo}
              </p>
            </div>
            {allDone && (
              <button
                onClick={dismissChecklist}
                className="rounded-lg px-2 py-1 text-[12px] font-semibold text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink"
              >
                {t.dashboard.start.dismiss}
              </button>
            )}
          </div>

          {/* Progress bar */}
          <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-deep-violet/[0.08]" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label={t.dashboard.start.title}>
            <div
              className="h-full rounded-full bg-gradient-to-r from-deep-violet via-magenta to-coral transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>

          <ol className="space-y-2">
            {checklistItems.map((item, index) => {
              const isDone = !!done[item.id];
              const isNext = nextItem?.id === item.id;
              return (
                <li
                  key={item.id}
                  className={`flex items-center gap-3 rounded-xl border p-3 transition ${
                    isDone
                      ? "border-transparent bg-ink/[0.02]"
                      : isNext
                        ? "border-deep-violet/30 bg-deep-violet/[0.04] shadow-sm"
                        : "border-ink/[0.06] bg-white"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold tabular-nums ${
                      isDone
                        ? "bg-deep-violet text-white"
                        : isNext
                          ? "bg-deep-violet text-white ring-4 ring-deep-violet/15"
                          : "bg-ink/[0.06] text-ink/45"
                    }`}
                  >
                    {isDone ? (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className={`text-[13px] font-semibold ${isDone ? "text-ink/40 line-through" : "text-ink"}`}>
                      {item.label}
                      {isNext && !isDone && (
                        <span className="ml-2 rounded-full bg-deep-violet px-2 py-0.5 align-middle text-[9px] font-bold uppercase tracking-wide text-white">
                          {t.dashboard.start.upNext}
                        </span>
                      )}
                    </p>
                  </div>
                  {isNext && !isDone ? (
                    <Link
                      href={item.href}
                      className="shrink-0 rounded-lg bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/30 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98]"
                    >
                      {t.dashboard.start.start}
                      <span aria-hidden> {dir === "rtl" ? "←" : "→"}</span>
                    </Link>
                  ) : (
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        onClick={() => toggleItem(item.id)}
                        aria-label={isDone ? t.dashboard.start.reopenStep.replace("{label}", item.label) : t.dashboard.start.markDone.replace("{label}", item.label)}
                        title={isDone ? t.dashboard.start.reopen : t.dashboard.start.skip}
                        className={`rounded-lg px-2 py-1 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                          isDone ? "text-ink/35 hover:text-ink/60" : "text-deep-violet/70 hover:bg-deep-violet/[0.06] hover:text-deep-violet"
                        }`}
                      >
                        {isDone ? t.dashboard.start.reopen : t.dashboard.start.skip}
                      </button>
                      <Link
                        href={item.href}
                        aria-label={t.dashboard.start.openStep.replace("{label}", item.label)}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/30 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                      >
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className="h-3.5 w-3.5">
                          <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </Link>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {/* Quick Actions */}
      <div className="grid gap-3 sm:grid-cols-3">
        {quickActions.map((action) => (
          <Link
            key={action.href}
            href={action.href}
            className="group rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-deep-violet/20 hover:shadow-lg hover:shadow-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:translate-y-0"
          >
            <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${action.color} text-white shadow-sm transition-transform duration-200 group-hover:scale-105`}>
              {action.icon}
            </div>
            <p className="text-[14px] font-bold text-ink transition-colors group-hover:text-deep-violet">{t.dashboard.actions[action.titleKey]}</p>
            <p className="mt-1 text-[12px] text-ink/50 leading-relaxed">{t.dashboard.actions[action.descKey]}</p>
          </Link>
        ))}
      </div>

      <BusinessPulse />

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statDefs.map((stat) => (
          <div key={stat.labelKey} className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm transition hover:shadow-md hover:shadow-deep-violet/[0.06]">
            <p className="text-[10px] sm:text-[11px] font-semibold uppercase tracking-wide text-ink/55">{t.dashboard.stats[stat.labelKey]}</p>
            <p className="mt-1 text-[20px] sm:text-[22px] font-bold text-ink">{stat.value}</p>
            <p className="text-[10px] text-ink/40">{t.dashboard.stats[stat.subKey]}</p>
          </div>
        ))}
      </div>

    </div>
  );
}
