"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { adminFetch, type AdminTenantDetail } from "@/lib/admin-api";

export default function AdminTenantDetailPage({ params }: { params: Promise<{ id: string }> }) {
  // Next 16: route params are async.
  const { id } = use(params);
  const [tenant, setTenant] = useState<AdminTenantDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminFetch<AdminTenantDetail>(`/api/v1/admin/tenants/${encodeURIComponent(id)}`)
      .then((t) => {
        if (!cancelled) setTenant(t);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Load failed.");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
        <p className="text-[14px] font-bold text-ink">{error}</p>
        <Link href="/tenants" className="mt-2 inline-block text-[12px] font-semibold text-deep-violet hover:underline">
          ← Back to tenants
        </Link>
      </div>
    );
  }

  if (!tenant) {
    return <div className="h-40 animate-pulse rounded-2xl border-2 border-white bg-white/60" aria-hidden />;
  }

  const name = [tenant.first_name, tenant.last_name].filter(Boolean).join(" ");

  return (
    <div className="space-y-4">
      <nav className="flex items-center gap-1.5 text-[12px] text-ink/40">
        <Link href="/tenants" className="font-medium hover:text-deep-violet">Tenants</Link>
        <span aria-hidden>›</span>
        <span className="font-semibold text-ink">{tenant.email}</span>
      </nav>

      <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
        <h1 className="text-[18px] font-bold text-ink">{tenant.email}</h1>
        <p className="mt-0.5 text-[12px] text-ink/50">
          {[name || null, tenant.email_verified ? "verified" : "unverified", tenant.created_at ? `joined ${new Date(tenant.created_at).toLocaleDateString()}` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: "Listing", value: tenant.listing_name ?? "—" },
            { label: "Last sync", value: tenant.last_synced_at ? new Date(tenant.last_synced_at).toLocaleString() : "—" },
            { label: "Reviews", value: String(tenant.reviews) },
            { label: "Posts / Banks", value: `${tenant.posts} / ${tenant.databanks}` },
          ].map((s) => (
            <div key={s.label} className="rounded-xl bg-ink/[0.03] px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink/45">{s.label}</p>
              <p className="mt-0.5 truncate text-[13px] font-bold text-ink" title={s.value}>{s.value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5">
          <h2 className="mb-3 text-[14px] font-bold text-ink">Recent reviews</h2>
          {tenant.recent_reviews.length === 0 ? (
            <p className="text-[12px] text-ink/40">No reviews synced yet.</p>
          ) : (
            <ul className="space-y-2">
              {tenant.recent_reviews.map((r) => (
                <li key={r.id} className="rounded-xl bg-ink/[0.03] p-3">
                  <p className="flex items-center justify-between text-[12px] font-semibold text-ink">
                    <span>{r.reviewer ?? "Google user"} · {r.rating}★ · {r.sentiment}</span>
                    {r.replied && <span className="text-[10px] font-bold uppercase text-emerald-600">replied</span>}
                  </p>
                  <p className="mt-1 line-clamp-2 text-[12px] text-ink/60">{r.text || "(star rating only)"}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5">
          <h2 className="mb-3 text-[14px] font-bold text-ink">Recent posts</h2>
          {tenant.recent_posts.length === 0 ? (
            <p className="text-[12px] text-ink/40">No posts yet.</p>
          ) : (
            <ul className="space-y-2">
              {tenant.recent_posts.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 rounded-xl bg-ink/[0.03] p-3">
                  <span className="truncate text-[12px] font-semibold text-ink">{p.title || "(untitled)"}</span>
                  <span className="shrink-0 rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/50">
                    {p.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
