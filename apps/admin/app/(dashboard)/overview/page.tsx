"use client";

import { useEffect, useState } from "react";
import { adminFetch, type AdminOverview } from "@/lib/admin-api";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink/55">{label}</p>
      <p className="mt-1 text-[24px] font-bold tabular-nums text-ink">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-ink/40">{sub}</p>}
    </div>
  );
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminFetch<AdminOverview>("/api/v1/admin/overview")
      .then((o) => {
        if (!cancelled) setData(o);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Load failed.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
        <p className="text-[14px] font-bold text-ink">Couldn&apos;t load overview.</p>
        <p className="mt-1 text-[12px] text-ink/50">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-hidden>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-2xl border-2 border-white bg-white/60" />
        ))}
      </div>
    );
  }

  const problems = data.outbox_failed + data.ingest_failed;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[20px] font-bold text-ink">Platform overview</h1>
        <p className="mt-0.5 text-[12px] text-ink/50">
          Tenants, content and pipeline health — read-only.
          {data.last_synced_at && ` · Last tenant sync ${new Date(data.last_synced_at).toLocaleString()}`}
        </p>
      </div>

      {problems > 0 && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[12px] font-medium text-red-700">
          {problems} failed item(s) need attention — {data.outbox_failed} outbox · {data.ingest_failed} ingest.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Tenants" value={String(data.users_total)} sub={`${data.users_verified} verified · ${data.signups_last_7d} new (7d)`} />
        <Stat label="Connected listings" value={String(data.connections)} />
        <Stat label="Reviews synced" value={String(data.reviews_total)} />
        <Stat
          label="Posts"
          value={String(data.posts_total)}
          sub={Object.entries(data.posts_by_status).map(([k, v]) => `${k}: ${v}`).join(" · ") || "none"}
        />
        <Stat label="Databanks" value={String(data.databanks_total)} sub={`${data.documents_total} documents`} />
        <Stat label="Outbox pending" value={String(data.outbox_pending)} />
        <Stat label="Outbox failed" value={String(data.outbox_failed)} />
        <Stat label="Ingest failed" value={String(data.ingest_failed)} />
      </div>
    </div>
  );
}
