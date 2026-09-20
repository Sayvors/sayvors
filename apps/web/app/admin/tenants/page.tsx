"use client";

import { useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";

interface Tenant {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  email_verified: boolean;
  created_at: string | null;
  has_connection: boolean;
  listing_name: string | null;
  last_synced_at: string | null;
  reviews: number;
  posts: number;
  databanks: number;
}

interface TenantDetail extends Tenant {
  recent_reviews: { rating?: number; review_text?: string | null; reviewer_name?: string | null }[];
  recent_posts: { title?: string; status?: string }[];
}

export default function AdminTenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TenantDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    adminFetch<{ items: Tenant[] }>("/api/v1/admin/tenants?limit=200")
      .then((d) => setTenants(d.items ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load tenants."))
      .finally(() => setLoading(false));
  }, []);

  async function toggleOpen(id: string) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await adminFetch<TenantDetail>(`/api/v1/admin/tenants/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load tenant.");
    } finally {
      setDetailLoading(false);
    }
  }

  const q = search.trim().toLowerCase();
  const filtered = q
    ? tenants.filter((t) =>
        t.email.toLowerCase().includes(q) ||
        `${t.first_name ?? ""} ${t.last_name ?? ""}`.toLowerCase().includes(q) ||
        (t.listing_name ?? "").toLowerCase().includes(q))
    : tenants;

  if (loading) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  return (
    <div className="space-y-4">
      {error && <p className="rounded-xl bg-coral/10 px-4 py-3 text-[12px] font-medium text-coral">{error}</p>}
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] text-ink/60">{tenants.length} tenants</p>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search email / name / listing…"
          className="input-field w-64"
        />
      </div>
      <div className="overflow-hidden rounded-2xl border border-white bg-white/80">
        <table className="w-full text-left text-[12.5px]">
          <thead>
            <tr className="border-b border-ink/[0.06] text-[10px] font-bold uppercase tracking-[0.1em] text-ink/40">
              <th className="px-4 py-3">Tenant</th>
              <th className="px-4 py-3">Listing</th>
              <th className="px-4 py-3 text-right">Reviews</th>
              <th className="px-4 py-3 text-right">Posts</th>
              <th className="px-4 py-3">Last sync</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <>
                <tr
                  key={t.id}
                  onClick={() => void toggleOpen(t.id)}
                  className="cursor-pointer border-b border-ink/[0.04] transition hover:bg-deep-violet/[0.03]"
                >
                  <td className="px-4 py-3">
                    <div className="font-semibold text-ink">{t.email}</div>
                    <div className="text-[11px] text-ink/45">{[t.first_name, t.last_name].filter(Boolean).join(" ") || "—"}</div>
                  </td>
                  <td className="px-4 py-3 text-ink/70">{t.has_connection ? t.listing_name ?? "connected" : <span className="text-ink/35">not connected</span>}</td>
                  <td className="px-4 py-3 text-right font-bold text-ink">{t.reviews}</td>
                  <td className="px-4 py-3 text-right font-bold text-ink">{t.posts}</td>
                  <td className="px-4 py-3 text-ink/55">{t.last_synced_at ? new Date(t.last_synced_at).toLocaleDateString() : "never"}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${t.email_verified ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                      {t.email_verified ? "Verified" : "Unverified"}
                    </span>
                  </td>
                </tr>
                {openId === t.id && (
                  <tr key={`${t.id}-detail`} className="border-b border-ink/[0.04] bg-deep-violet/[0.02]">
                    <td colSpan={6} className="px-4 py-4">
                      {detailLoading ? (
                        <LogoLoader size={18} />
                      ) : detail ? (
                        <div className="grid gap-4 sm:grid-cols-2">
                          <div>
                            <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Recent reviews</p>
                            {(detail.recent_reviews ?? []).length === 0 ? (
                              <p className="mt-1 text-[12px] text-ink/35">none</p>
                            ) : (
                              <ul className="mt-1 space-y-1">
                                {detail.recent_reviews.slice(0, 5).map((r, i) => (
                                  <li key={i} className="text-[12px] text-ink/70">
                                    {"★".repeat(r.rating ?? 0)} {r.reviewer_name ?? "—"}: {(r.review_text ?? "").slice(0, 60) || "(no text)"}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                          <div>
                            <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Recent posts</p>
                            {(detail.recent_posts ?? []).length === 0 ? (
                              <p className="mt-1 text-[12px] text-ink/35">none</p>
                            ) : (
                              <ul className="mt-1 space-y-1">
                                {detail.recent_posts.slice(0, 5).map((p, i) => (
                                  <li key={i} className="text-[12px] text-ink/70">
                                    {p.title ?? "Untitled"} — {p.status ?? "?"}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </div>
                      ) : (
                        <p className="text-[12px] text-ink/40">Could not load detail.</p>
                      )}
                    </td>
                  </tr>
                )}
              </>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-[12px] text-ink/35">No tenants match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
