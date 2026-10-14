"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";
import { ErrorState, PageHeader, Panel, SectionTitle, Tile } from "../admin-ui";

interface Overview {
  users_total: number;
  users_verified: number;
  signups_last_7d: number;
  connections: number;
  last_synced_at: string | null;
  reviews_total: number;
  posts_total: number;
  posts_by_status: Record<string, number>;
  replies_by_status: Record<string, number>;
  media_by_status: Record<string, number>;
  databanks_total: number;
  documents_total: number;
  outbox_pending: number;
  outbox_failed: number;
  ingest_failed: number;
}

interface UsageTotals {
  calls: number;
  total_tokens: number;
  tenants: number;
}

interface HealthLite {
  status: string;
  services: { name: string; kind: string; ok: boolean; detail: string }[];
}

const STATUS_ORDER = [
  "published", "scheduled", "pending_approval", "draft", "posted",
  "failed", "rejected", "approved", "archived", "sent",
];

/**
 * Counts arrive from an API we do not control. Formatting defensively is not
 * paranoia: a missing field once crashed the page with "Cannot read
 * properties of undefined", which is exactly the raw-error leak the audit
 * flagged. A dash reads as "not reported"; a crash reads as "broken".
 */
function n(value: number | undefined | null): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "—";
}

/**
 * Status breakdown. `failed` is the only count that earns colour — every
 * other state is ink, because colour here means "something is wrong", not
 * "this is a category".
 */
function StatusCounts({ title, map }: { title: string; map: Record<string, number> }) {
  const safe = map ?? {};
  const keys = Object.keys(safe).sort((a, b) => {
    const ia = STATUS_ORDER.indexOf(a);
    const ib = STATUS_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return (
    <Panel>
      <SectionTitle>{title}</SectionTitle>
      <div className="flex flex-wrap gap-x-[var(--ad-s)] gap-y-[var(--ad-3xs)]">
        {keys.length === 0 && <span className="text-admin-base text-ink/40">none</span>}
        {keys.map((k) => (
          <span key={k} className="text-admin-base">
            <span
              className={`font-bold tabular-nums ${
                k === "failed" ? "text-coral" : "text-ink"
              }`}
            >
              {n(safe[k])}
            </span>{" "}
            <span className="text-ink/50">{k.replace(/_/g, " ")}</span>
          </span>
        ))}
      </div>
    </Panel>
  );
}

export default function AdminOverviewPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [totals, setTotals] = useState<UsageTotals | null>(null);
  const [health, setHealth] = useState<HealthLite | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    // Each source degrades on its own: a failing health probe must not blank
    // the tenant counts an operator came here to read.
    const [o, t, h] = await Promise.allSettled([
      adminFetch<Overview>("/api/v1/admin/overview"),
      adminFetch<{ totals?: UsageTotals }>("/api/v1/admin/usage/overview"),
      adminFetch<HealthLite>("/api/v1/admin/health"),
    ]);
    if (o.status === "fulfilled") setOverview(o.value);
    else setError("Could not load the overview.");
    setTotals(t.status === "fulfilled" ? t.value?.totals ?? null : null);
    setHealth(h.status === "fulfilled" ? h.value : null);
    setLoading(false);
  }

  useEffect(() => {
    void load();
  }, []);

  if (loading && !overview) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  const broken: string[] = [];
  const posts = overview?.posts_by_status ?? {};
  const replies = overview?.replies_by_status ?? {};
  const media = overview?.media_by_status ?? {};
  if (overview) {
    if ((overview.outbox_failed ?? 0) > 0) broken.push(`${overview.outbox_failed} outbox events failed`);
    if ((overview.ingest_failed ?? 0) > 0) broken.push(`${overview.ingest_failed} databank ingests failed`);
    if ((posts.failed ?? 0) > 0) broken.push(`${posts.failed} posts failed to publish`);
    if ((replies.failed ?? 0) > 0) broken.push(`${replies.failed} replies failed`);
    if ((media.failed ?? 0) > 0) broken.push(`${media.failed} photos failed`);
    if ((overview.connections ?? 0) === 0) broken.push("No Localith listings connected");
  }
  const downServices = (health?.services ?? []).filter((s) => !s.ok);

  return (
    <div className="admin-ui">
      <PageHeader
        title="Overview"
        lede="Platform health first, then volume."
      />

      {error && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Overview unavailable" detail={error} onRetry={() => void load()} />
        </div>
      )}

      {overview && (
        <div className="space-y-[var(--ad-m)]">
          {/* The memorable moment: one coral rail owns the top of the page
              whenever anything is failing, and disappears entirely when
              nothing is. No competing "everything is fine" badge. */}
          {(broken.length > 0 || downServices.length > 0) && (
            <section
              aria-labelledby="broken-now"
              className="rounded-admin-card border border-coral/40 bg-coral/[0.05] p-[var(--ad-s)]"
            >
              <h2 id="broken-now" className="text-admin-base font-bold uppercase tracking-wide text-coral">
                Broken right now
              </h2>
              <ul className="mt-[var(--ad-xs)] space-y-[var(--ad-3xs)]">
                {broken.map((b) => (
                  <li key={b} className="flex items-start gap-[var(--ad-2xs)] text-admin-base text-ink">
                    <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                    {b}
                  </li>
                ))}
                {downServices.map((s) => (
                  <li key={s.name} className="flex items-start gap-[var(--ad-2xs)] text-admin-base text-ink">
                    <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                    {s.name} down{s.detail ? ` — ${s.detail}` : ""}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-labelledby="the-business">
            <h2 id="the-business">
              <SectionTitle>The business</SectionTitle>
            </h2>
            <div className="grid gap-[var(--ad-xs)] sm:grid-cols-3 lg:grid-cols-4">
              <Tile label="Tenants" value={n(overview.users_total)} />
              <Tile label="Verified" value={n(overview.users_verified)} />
              <Tile label="Signups 7d" value={n(overview.signups_last_7d)} />
              <Tile label="Connected listings" value={n(overview.connections)} />
              <Tile label="Reviews" value={n(overview.reviews_total)} />
              <Tile label="Posts" value={n(overview.posts_total)} />
              <Tile
                label="Databanks / docs"
                value={`${n(overview.databanks_total)} / ${n(overview.documents_total)}`}
              />
              <Tile
                label="AI calls / tokens"
                value={
                  totals
                    ? `${n(totals.calls)} / ${n(totals.total_tokens)}`
                    : "—"
                }
              />
            </div>
          </section>

          <section className="grid gap-[var(--ad-xs)] sm:grid-cols-2">
            <StatusCounts title="Replies by status" map={overview.replies_by_status} />
            <StatusCounts title="Posts by status" map={overview.posts_by_status} />
            <StatusCounts title="Media by status" map={overview.media_by_status} />
            <Panel>
              <SectionTitle>Pipeline</SectionTitle>
              <div className="space-y-[var(--ad-3xs)] text-admin-base">
                <div><span className="font-bold tabular-nums text-ink">{n(overview.outbox_pending)}</span> <span className="text-ink/50">outbox pending</span></div>
                <div><span className={`font-bold tabular-nums ${overview.outbox_failed ? "text-coral" : "text-ink"}`}>{n(overview.outbox_failed)}</span> <span className="text-ink/50">outbox failed</span></div>
                <div><span className={`font-bold tabular-nums ${overview.ingest_failed ? "text-coral" : "text-ink"}`}>{n(overview.ingest_failed)}</span> <span className="text-ink/50">ingests failed</span></div>
              </div>
            </Panel>
          </section>

          <p className="text-admin-micro text-ink/45">
            Last Localith sync:{" "}
            {overview.last_synced_at ? new Date(overview.last_synced_at).toLocaleString() : "never"}
            {" · "}
            <Link href="/admin/tenants" className="font-semibold text-deep-violet hover:underline">Tenants →</Link>
            {" · "}
            <Link href="/admin/health" className="font-semibold text-deep-violet hover:underline">Health →</Link>
          </p>
        </div>
      )}
    </div>
  );
}