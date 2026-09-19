"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";
import { apiFetch } from "@/lib/api-rag";
import { dedupeBusinesses } from "@/lib/channel-identity";
import { fetchOverview } from "@/lib/api-analytics";

interface AutoReply {
  channel_id: string;
  enabled: boolean;
  tone: string;
  min_rating_auto: number;
  model: string;
  approval_mode?: string;
  custom_instructions?: string | null;
}

interface GoogleChannel {
  id: string;
  display_name: string | null;
  status: string;
  listing_id?: string | null;
  source?: string | null;
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">{label}</p>
      <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{value}</p>
      {sub && <p className="text-[11px] text-ink/30 dark:text-fog/30">{sub}</p>}
    </div>
  );
}

export default function AutomationsPage() {
  const [channels, setChannels] = useState<GoogleChannel[]>([]);
  const [configs, setConfigs] = useState<Record<string, AutoReply>>({});
  const [pending, setPending] = useState<Record<string, number>>({});
  const [overview, setOverview] = useState<{ response_rate: number; unanswered: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        if (cancelled) return;
        const google: GoogleChannel[] = dedupeBusinesses(
          (data.channels ?? []).filter(
            (c: { platform: string }) => c.platform === "google_reviews"
          )
        );
        setChannels(google);
        const cfgs: Record<string, AutoReply> = {};
        const pend: Record<string, number> = {};
        await Promise.all(
          google.map(async (c) => {
            try {
              cfgs[c.id] = await apiFetch(`/api/v1/channels/${c.id}/autoreply`);
            } catch {
              /* default config is created server-side on first GET */
            }
            try {
              const r = await apiFetch(`/api/v1/channels/${c.id}/reviews?status=pending_approval&limit=1`);
              pend[c.id] = r.pending ?? 0;
            } catch {
              pend[c.id] = 0;
            }
          })
        );
        if (!cancelled) {
          setConfigs(cfgs);
          setPending(pend);
        }
      } catch {
        /* backend down — empty state renders */
      }
      try {
        const o = await fetchOverview(30);
        if (!cancelled) setOverview({ response_rate: o.response_rate, unanswered: o.unanswered });
      } catch {
        /* stats stay dash */
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const pendingTotal = useMemo(
    () => channels.reduce((sum, c) => sum + (pending[c.id] ?? 0), 0),
    [channels, pending]
  );

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Automations" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Automations</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          Your Google Review auto-reply engine — AI drafts, you approve.
        </p>
      </div>

      {banner && (
        <div
          role="status"
          className={`rounded-xl border p-3 text-[13px] ${
            banner.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-600"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span>{banner.text}</span>
            <button
              onClick={() => setBanner(null)}
              aria-label="Dismiss"
              className="rounded p-0.5 text-current/60 transition hover:opacity-70"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Locations connected" value={String(channels.length)} sub="Google Business" />
        <StatCard label="Pending approval" value={String(pendingTotal)} sub="awaiting you" />
        <StatCard
          label="Response rate"
          value={overview ? `${overview.response_rate}%` : "—"}
          sub="last 30 days"
        />
        <StatCard
          label="Awaiting reply"
          value={overview ? String(overview.unanswered) : "—"}
          sub="all locations"
        />
      </div>

      {/* Locations */}
      {loading ? (
        <div className="space-y-2" role="status" aria-label="Loading automations">
          {[0, 1].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-ink/[0.05] dark:bg-fog/[0.05]" />
          ))}
        </div>
      ) : channels.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-ink/[0.06] bg-white py-14 text-center dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[14px] font-semibold text-ink/70 dark:text-fog/70">No Google Business locations yet</p>
          <p className="max-w-sm text-[12px] text-ink/45 dark:text-fog/45">
            Connect your Google Business Profile to put the review auto-reply engine to work.
          </p>
          <Link
            href="/dashboard/channels"
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
          >
            Connect Google Business
          </Link>
        </div>
      ) : (
        <div className="space-y-2.5">
          {channels.map((c) => {
            const cfg = configs[c.id];
            const approvalMode = cfg?.approval_mode === "approval" ? "You approve all" : "Automatic above threshold";
            const pendingCount = pending[c.id] ?? 0;
            return (
              <div
                key={c.id}
                className="flex flex-wrap items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold text-ink dark:text-fog">
                    {c.display_name || "Business location"}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-600">
                      Engine on
                    </span>
                    <span className="rounded bg-deep-violet/[0.06] px-1.5 py-0.5 text-[10px] font-medium text-deep-violet">
                      {approvalMode}
                    </span>
                    {cfg?.approval_mode !== "approval" && (
                      <span className="rounded bg-ink/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-ink/45 dark:bg-fog/[0.04] dark:text-fog/45">
                        auto-post ★{cfg?.min_rating_auto ?? 4}+
                      </span>
                    )}
                    {pendingCount > 0 && (
                      <Link
                        href="/dashboard/analytics"
                        className="rounded bg-amber/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 transition hover:bg-amber/20"
                      >
                        {pendingCount} pending approval
                      </Link>
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-[11px] font-medium text-ink/40 dark:text-fog/40">
                      Tone: {cfg?.tone ?? "friendly"}
                    </span>
                    <Link
                      href="/dashboard/settings"
                      className="text-[11px] font-semibold text-deep-violet hover:underline"
                    >
                      Change in Configuration
                    </Link>
                  </div>
                </div>
                <Link
                  href="/dashboard/channels"
                  className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06]"
                >
                  AI settings
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
