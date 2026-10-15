"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";
import { ErrorState, Freshness, PageHeader, Panel, SectionTitle, Table, Td, Th, Tile } from "../admin-ui";

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

interface UsageBreakdown {
  days: number;
  totals: UsageTotals;
  per_tenant: { tenant_id: string | null; email: string; calls: number; total_tokens: number; avg_latency_ms: number; last_seen: string | null }[];
  per_model: { model: string; api_model: string; calls: number; total_tokens: number }[];
  daily: { day: string; total_tokens: number; calls: number }[];
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
 * Counts arrive from an API we do not control, so formatting is defensive.
 * But it is also FACTUAL: a real 0 and a field the API never sent are
 * different facts, and rendering both as "0" is a lie the operator cannot
 * see through. A missing value says so; it never borrows a number's meaning.
 */
function n(value: number | undefined | null): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "not reported";
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
  const [totals, setTotals] = useState<UsageBreakdown | null>(null);
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
      adminFetch<UsageBreakdown>("/api/v1/admin/usage/overview"),
      adminFetch<HealthLite>("/api/v1/admin/health"),
    ]);
    if (o.status === "fulfilled") setOverview(o.value);
    else setError("Could not load the overview.");
    setTotals(t.status === "fulfilled" ? t.value ?? null : null);
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
      {/* No editorial lede. "Platform health first, then volume" was a caption
          written for a reader, not a fact about the platform. What an operator
          needs first is WHEN the numbers were measured. */}
      <PageHeader title="Overview" actions={<Freshness at={overview?.last_synced_at} />} />

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
              <Tile label="Signed up (7d)" value={n(overview.signups_last_7d)} />
              <Tile label="Connected listings" value={n(overview.connections)} />
              <Tile label="Reviews" value={n(overview.reviews_total)} />
              <Tile label="Posts" value={n(overview.posts_total)} />
              <Tile
                label="Databanks"
                rows={[
                  { label: "databanks", value: n(overview.databanks_total) },
                  { label: "documents", value: n(overview.documents_total) },
                ]}
              />
              <Tile
                label="AI usage"
                rows={[
                  { label: "calls", value: n(totals?.totals?.calls) },
                  { label: "tokens", value: n(totals?.totals?.total_tokens) },
                ]}
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

          {/* Usage breakdown: the totals tile above says how much; these tables
              say where it went. Without them a spike is undiagnosable. */}
          {totals && (totals.per_model.length > 0 || totals.per_tenant.length > 0) && (
            <section className="grid gap-[var(--ad-xs)] lg:grid-cols-2">
              <Panel>
                <SectionTitle>AI usage by model ({totals.days}d)</SectionTitle>
                {totals.per_model.length === 0 ? (
                  <p className="text-admin-base text-ink/40">No model usage.</p>
                ) : (
                  <Table minWidth={480}>
                    <thead>
                      <tr className="border-b border-ink/[0.06]">
                        <Th>Model</Th>
                        <Th align="right">Calls</Th>
                        <Th align="right">Tokens</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {totals.per_model.map((m) => (
                        <tr key={m.model} className="border-b border-ink/[0.04]">
                          <Td className="text-ink/75">{m.model}</Td>
                          <Td align="right" className="tabular-nums text-ink">
                            {n(m.calls)}
                          </Td>
                          <Td align="right" className="tabular-nums text-ink">
                            {n(m.total_tokens)}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </Panel>

              <Panel>
                <SectionTitle>AI usage by tenant ({totals.days}d)</SectionTitle>
                {totals.per_tenant.length === 0 ? (
                  <p className="text-admin-base text-ink/40">No tenant usage.</p>
                ) : (
                  <Table minWidth={560}>
                    <thead>
                      <tr className="border-b border-ink/[0.06]">
                        <Th>Tenant</Th>
                        <Th align="right">Calls</Th>
                        <Th align="right">Tokens</Th>
                        <Th>Last seen</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {totals.per_tenant
                        .slice()
                        .sort((a, b) => b.calls - a.calls)
                        .slice(0, 10)
                        .map((t) => (
                          <tr key={t.tenant_id} className="border-b border-ink/[0.04]">
                            <Td className="text-ink/75">{t.email}</Td>
                            <Td align="right" className="tabular-nums text-ink">
                              {n(t.calls)}
                            </Td>
                            <Td align="right" className="tabular-nums text-ink">
                              {n(t.total_tokens)}
                            </Td>
                            <Td className="text-ink/55">
                              {t.last_seen
                                ? new Date(t.last_seen).toLocaleDateString()
                                : "never"}
                            </Td>
                          </tr>
                        ))}
                    </tbody>
                  </Table>
                )}
                {totals.per_tenant.length > 10 && (
                  <p className="mt-[var(--ad-2xs)] text-admin-micro text-ink/45">
                    Top 10 of {totals.per_tenant.length} by calls.
                  </p>
                )}
              </Panel>
            </section>
          )}

          {totals && totals.daily.length > 0 && (
            <section>
              <Panel>
                <SectionTitle>Daily tokens ({totals.days}d)</SectionTitle>
                <div className="flex h-24 items-end gap-[2px]">
                  {totals.daily.map((d) => {
                    const max = Math.max(...totals.daily.map((x) => x.total_tokens), 1);
                    const pct = Math.max(4, Math.round((d.total_tokens / max) * 100));
                    return (
                      <div
                        key={d.day}
                        className="group relative flex-1 rounded-t bg-deep-violet/70 transition-colors hover:bg-deep-violet"
                        style={{ height: `${pct}%` }}
                      >
                        <span className="pointer-events-none absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-admin-ctl bg-ink px-2 py-1 text-admin-micro font-bold text-white opacity-0 transition-opacity group-hover:opacity-100">
                          {d.day}: {d.total_tokens.toLocaleString()} tok
                        </span>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-[var(--ad-2xs)] text-admin-micro text-ink/45">
                  {totals.daily.length} days. Hover a bar for exact figures.
                </p>
              </Panel>
            </section>
          )}

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