"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";

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

function Tile({ label, value, broken }: { label: string; value: number | string; broken?: boolean }) {
  return (
    <div className={`rounded-2xl border p-4 ${broken ? "border-coral/30 bg-coral/[0.04]" : "border-white bg-white/80"}`}>
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{label}</div>
      <div className={`mt-2 text-[24px] font-bold ${broken ? "text-coral" : "text-ink"}`}>{value}</div>
    </div>
  );
}

function StatusCounts({ title, map }: { title: string; map: Record<string, number> }) {
  const order = ["published", "scheduled", "pending_approval", "draft", "posted", "failed", "rejected", "approved", "archived", "sent"];
  const keys = Object.keys(map).sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return (
    <div className="rounded-2xl border border-white bg-white/80 p-4">
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{title}</div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {keys.length === 0 && <span className="text-[13px] text-ink/30">none</span>}
        {keys.map((k) => (
          <span key={k} className="text-[13px]">
            <span className={k === "failed" ? "font-bold text-coral" : "font-bold text-ink"}>{map[k]}</span>
            <span className="ml-1 text-ink/45">{k}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function AdminOverviewPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [totals, setTotals] = useState<UsageTotals | null>(null);
  const [health, setHealth] = useState<HealthLite | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [o, u, h] = await Promise.all([
        adminFetch<Overview>("/api/v1/admin/overview").catch(() => null),
        adminFetch<{ totals?: UsageTotals }>("/api/v1/admin/usage/overview").then((r) => r?.totals ?? null).catch(() => null),
        adminFetch<HealthLite>("/api/v1/admin/health").catch(() => null),
      ]);
      if (o) setOverview(o);
      if (u) setTotals(u);
      if (h) setHealth(h);
      if (!o && !h) setError("Could not load admin data — is the API running?");
      setLoading(false);
    })();
  }, []);

  const broken: string[] = [];
  if (overview) {
    if (overview.outbox_failed > 0) broken.push(`${overview.outbox_failed} outbox events failed`);
    if (overview.ingest_failed > 0) broken.push(`${overview.ingest_failed} databank ingests failed`);
    if ((overview.posts_by_status.failed ?? 0) > 0) broken.push(`${overview.posts_by_status.failed} posts failed to publish`);
    if ((overview.replies_by_status.failed ?? 0) > 0) broken.push(`${overview.replies_by_status.failed} replies failed`);
    if ((overview.media_by_status.failed ?? 0) > 0) broken.push(`${overview.media_by_status.failed} photos failed`);
    if ((overview.connections ?? 0) === 0) broken.push("No Localith listings connected");
  }
  const downServices = (health?.services ?? []).filter((s) => !s.ok);

  if (loading) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  return (
    <div className="space-y-5">
      {error && <p className="rounded-xl bg-coral/10 px-4 py-3 text-[12px] font-medium text-coral">{error}</p>}
      {overview && (
        <>
          {/* What's broken first — admin opens this page to see problems */}
          {(broken.length > 0 || downServices.length > 0) && (
            <section className="rounded-2xl border border-coral/30 bg-coral/[0.04] p-4">
              <h2 className="text-[13px] font-bold uppercase tracking-wide text-coral">Broken right now</h2>
              <ul className="mt-2 space-y-1">
                {broken.map((b) => (
                  <li key={b} className="flex items-center gap-2 text-[13px] text-ink">
                    <span className="h-1.5 w-1.5 rounded-full bg-coral" aria-hidden /> {b}
                  </li>
                ))}
                {downServices.map((s) => (
                  <li key={s.name} className="flex items-center gap-2 text-[13px] text-ink">
                    <span className="h-1.5 w-1.5 rounded-full bg-coral" aria-hidden /> {s.name} down{s.detail ? ` — ${s.detail}` : ""}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h2 className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">The business</h2>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
              <Tile label="Tenants" value={overview.users_total} />
              <Tile label="Verified" value={overview.users_verified} />
              <Tile label="Signups 7d" value={overview.signups_last_7d} />
              <Tile label="Connected listings" value={overview.connections} />
              <Tile label="Reviews" value={overview.reviews_total} />
              <Tile label="Posts" value={overview.posts_total} />
              <Tile label="Databanks / docs" value={`${overview.databanks_total} / ${overview.documents_total}`} />
              <Tile label="AI calls / tokens" value={totals ? `${totals.calls} / ${totals.total_tokens.toLocaleString()}` : "—"} />
            </div>
          </section>

          <section className="grid gap-3 sm:grid-cols-2">
            <StatusCounts title="Replies by status" map={overview.replies_by_status} />
            <StatusCounts title="Posts by status" map={overview.posts_by_status} />
            <StatusCounts title="Media by status" map={overview.media_by_status} />
            <div className="rounded-2xl border border-white bg-white/80 p-4">
              <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Pipeline</div>
              <div className="mt-2 space-y-1 text-[13px]">
                <div><span className="font-bold text-ink">{overview.outbox_pending}</span> <span className="text-ink/45">outbox pending</span></div>
                <div><span className={`font-bold ${overview.outbox_failed ? "text-coral" : "text-ink"}`}>{overview.outbox_failed}</span> <span className="text-ink/45">outbox failed</span></div>
                <div><span className={`font-bold ${overview.ingest_failed ? "text-coral" : "text-ink"}`}>{overview.ingest_failed}</span> <span className="text-ink/45">ingests failed</span></div>
              </div>
            </div>
          </section>

          <p className="text-[11px] text-ink/40">
            Last Localith sync: {overview.last_synced_at ? new Date(overview.last_synced_at).toLocaleString() : "never"} ·{" "}
            <Link href="/admin/tenants" className="font-semibold text-deep-violet hover:underline">Tenants →</Link>{" "}
            <Link href="/admin/health" className="ml-3 font-semibold text-deep-violet hover:underline">Health →</Link>
          </p>
        </>
      )}
    </div>
  );
}
