"use client";

import { useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import {
  ErrorState,
  PageHeader,
  Pill,
  Table,
  TableScroll,
  Td,
  Th,
} from "../admin-ui";
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
  recent_reviews: { rating?: number; text?: string | null; reviewer?: string | null }[];
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

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const d = await adminFetch<{ items: Tenant[] }>("/api/v1/admin/tenants?limit=200");
      setTenants(d.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load tenants.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
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
    <div className="admin-ui">
      <PageHeader
        title="Tenants"
        actions={
          <>
            {/* Only meaningful once a filter is active. "12 of 12 shown"
                unfiltered is noise that looks like a fact. */}
            {q && (
              <span className="text-admin-base text-ink/55">
                <span className="font-bold tabular-nums text-ink">
                  {filtered.length}
                </span>{" "}
                of <span className="tabular-nums">{tenants.length}</span> match
              </span>
            )}
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search email / name / listing"
              aria-label="Search tenants"
              type="search"
              className="input-field w-full max-w-64"
            />
          </>
        }
      />
      {error && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Tenants unavailable" detail={error} onRetry={() => void load()} />
        </div>
      )}

      {/* TableScroll: overflow-x-auto, not overflow-hidden. Hidden CLIPPED the
          Posts / Databanks / Last sync columns at 390px, leaving them
          unreachable. overflow-y-hidden still holds the rounded corners. */}
      <TableScroll>
        <Table minWidth={760}>
          <thead>
            <tr className="border-b border-ink/[0.06]">
              <Th>Tenant</Th>
              <Th>Listing</Th>
              <Th align="right">Reviews</Th>
              <Th align="right">Posts</Th>
              <Th>Last sync</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-[var(--ad-s)] py-[var(--ad-m)] text-center text-admin-base text-ink/45">
                  {q ? `No tenant matches "${search}".` : "No tenants yet."}
                </td>
              </tr>
            )}
            {filtered.map((t) => (
              <>
                <tr
                  key={t.id}
                  onClick={() => void toggleOpen(t.id)}
                  className="cursor-pointer border-b border-ink/[0.04] transition hover:bg-deep-violet/[0.03]"
                >
                  <Td>
                    <div className="font-semibold text-ink">{t.email}</div>
                    <div className="text-admin-micro text-ink/50">{[t.first_name, t.last_name].filter(Boolean).join(" ") || "—"}</div>
                  </Td>
                  <Td className="text-ink/70">{t.has_connection ? t.listing_name ?? "connected" : <span className="text-ink/35">not connected</span>}</Td>
                  <Td align="right" className="font-bold text-ink">{t.reviews.toLocaleString()}</Td>
                  <Td align="right" className="font-bold text-ink">{t.posts.toLocaleString()}</Td>
                  <Td className="text-ink/55">{t.last_synced_at ? new Date(t.last_synced_at).toLocaleDateString() : "never"}</Td>
                  <Td>
                    <Pill tone={t.email_verified ? "ok" : "warn"}>
                      {t.email_verified ? "Verified" : "Unverified"}
                    </Pill>
                  </Td>
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
                                    {"★".repeat(r.rating ?? 0)} {r.reviewer ?? "—"}: {(r.text ?? "").slice(0, 60) || "(no text)"}
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
        </Table>
      </TableScroll>
    </div>
  );
}
