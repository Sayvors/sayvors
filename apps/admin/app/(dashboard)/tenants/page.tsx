"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { adminFetch, type AdminTenant } from "@/lib/admin-api";

const PAGE_SIZE = 25;

export default function AdminTenantsPage() {
  const [items, setItems] = useState<AdminTenant[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    if (searchInput.trim() === search) return;
    debounce.current = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(0);
    }, 350);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [searchInput, search]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
    if (search) q.set("search", search);
    adminFetch<{ total: number; items: AdminTenant[] }>(`/api/v1/admin/tenants?${q.toString()}`)
      .then((d) => {
        if (cancelled) return;
        setItems(d.items);
        setTotal(d.total);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Load failed.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [search, page]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Tenants</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">{total} registered users</p>
        </div>
        <input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search email or name…"
          aria-label="Search tenants"
          className="input-field w-56"
        />
      </div>

      {error ? (
        <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border-2 border-white bg-white/80">
          <table className="w-full min-w-[720px] text-left text-[12px]">
            <thead>
              <tr className="border-b border-ink/[0.06] text-ink/45">
                <th className="px-4 py-2.5 font-semibold">User</th>
                <th className="px-4 py-2.5 font-semibold">Listing</th>
                <th className="px-4 py-2.5 text-right font-semibold">Reviews</th>
                <th className="px-4 py-2.5 text-right font-semibold">Posts</th>
                <th className="px-4 py-2.5 text-right font-semibold">Banks</th>
                <th className="px-4 py-2.5 text-right font-semibold">Joined</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-ink/[0.04]">
                    <td colSpan={6} className="px-4 py-3">
                      <div className="h-3 animate-pulse rounded bg-ink/[0.06]" />
                    </td>
                  </tr>
                ))
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink/40">
                    No tenants found.
                  </td>
                </tr>
              ) : (
                items.map((t) => (
                  <tr key={t.id} className="border-b border-ink/[0.04] transition last:border-0 hover:bg-deep-violet/[0.03]">
                    <td className="px-4 py-2.5">
                      <Link href={`/tenants/${t.id}`} className="font-semibold text-deep-violet hover:underline">
                        {t.email}
                      </Link>
                      <span className="ml-2 text-[11px] text-ink/40">
                        {[t.first_name, t.last_name].filter(Boolean).join(" ") || "—"}
                        {t.email_verified ? " · verified" : " · unverified"}
                      </span>
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-2.5 text-ink/70">{t.listing_name ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{t.reviews}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{t.posts}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{t.databanks}</td>
                    <td className="px-4 py-2.5 text-right text-ink/45">
                      {t.created_at ? new Date(t.created_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="btn-secondary !px-3 !py-1.5 disabled:opacity-40"
          >
            Prev
          </button>
          <span className="text-[11px] text-ink/40">Page {page + 1} of {pages}</span>
          <button
            onClick={() => setPage(Math.min(pages - 1, page + 1))}
            disabled={page >= pages - 1}
            className="btn-secondary !px-3 !py-1.5 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
