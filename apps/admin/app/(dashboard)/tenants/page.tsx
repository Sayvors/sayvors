"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { adminFetch, type AdminOverview, type AdminTenant } from "@/lib/admin-api";

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;
const DEFAULT_SIZE = 25;

type FilterKey = "all" | "verified" | "unverified" | "connected" | "not_connected";
type SortKey = "newest" | "oldest" | "reviews" | "posts";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}
function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return fmtDate(iso);
}
function initials(t: AdminTenant): string {
  const a = (t.first_name?.[0] ?? t.email[0] ?? "?").toUpperCase();
  const b = (t.last_name?.[0] ?? t.email[1] ?? "").toUpperCase();
  return (a + (b && b !== a ? b : "")).slice(0, 2);
}
function pct(part: number, whole: number): number {
  if (!whole) return 0;
  return Math.round((part / whole) * 100);
}

export default function AdminTenantsPage() {
  const [items, setItems] = useState<AdminTenant[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_SIZE);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<SortKey>("newest");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // overview for accurate global stats
  useEffect(() => {
    adminFetch<AdminOverview>("/api/v1/admin/overview").then(setOverview).catch(() => {});
  }, []);

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
    const q = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
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
  }, [search, page, pageSize]);

  const pages = Math.max(1, Math.ceil(total / pageSize));
  const rangeStart = total === 0 ? 0 : page * pageSize + 1;
  const rangeEnd = Math.min(total, (page + 1) * pageSize);

  // client filter/sort for current page (fast scan aid; server search stays authoritative)
  const visible = useMemo(() => {
    let out = [...items];
    if (filter === "verified") out = out.filter((t) => t.email_verified);
    else if (filter === "unverified") out = out.filter((t) => !t.email_verified);
    else if (filter === "connected") out = out.filter((t) => t.has_connection);
    else if (filter === "not_connected") out = out.filter((t) => !t.has_connection);
    switch (sort) {
      case "newest":
        out.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
        break;
      case "oldest":
        out.sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
        break;
      case "reviews":
        out.sort((a, b) => b.reviews - a.reviews);
        break;
      case "posts":
        out.sort((a, b) => b.posts - a.posts);
        break;
    }
    return out;
  }, [items, filter, sort]);

  const filterCounts = useMemo(() => {
    return {
      all: items.length,
      verified: items.filter((t) => t.email_verified).length,
      unverified: items.filter((t) => !t.email_verified).length,
      connected: items.filter((t) => t.has_connection).length,
      not_connected: items.filter((t) => !t.has_connection).length,
    };
  }, [items]);

  const hasActiveFilter = filter !== "all";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-[20px] font-bold tracking-tight text-ink">Tenants</h1>
            <p className="mt-1 max-w-[560px] text-[12px] leading-relaxed text-ink/50">
              Every account that signed up — verify status, listing connection and content at a glance. Search is server-side; filters refine the current page.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-ink/60 ring-1 ring-ink/[0.06]">
                <span className="h-2 w-2 rounded-full bg-deep-violet" aria-hidden />
                {total.toLocaleString()} total
              </span>
              {overview && (
                <>
                  <span className="hidden text-ink/20 sm:inline">·</span>
                  <span className="text-ink/45">
                    {pct(overview.users_verified, overview.users_total)}% verified · {pct(overview.connections, overview.users_total)}% connected
                  </span>
                </>
              )}
              {!search && !loading && <span className="text-ink/30">· Showing {rangeStart}–{rangeEnd}</span>}
              {search && <span className="rounded-full bg-amber-50 px-2 py-1 font-medium text-amber-700 ring-1 ring-amber-200">search: “{search}”</span>}
            </div>
          </div>

          <div className="flex w-full shrink-0 flex-col gap-2 sm:w-[320px]">
            <div className="relative">
              <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink/30">
                <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.7" />
                <path d="M15.5 15.5L19 19" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search email or name…"
                aria-label="Search tenants by email or name"
                className="w-full rounded-xl border border-ink/[0.08] bg-white py-2.5 pl-9 pr-9 text-[13px] text-ink placeholder:text-ink/35 outline-none transition focus:border-deep-violet/30 focus:ring-4 focus:ring-deep-violet/10"
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={() => setSearchInput("")}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1.5 text-ink/30 transition hover:bg-ink/[0.06] hover:text-ink"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path d="M7 7l10 10M17 7L7 17" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                  </svg>
                </button>
              )}
            </div>
            <p className="hidden text-right text-[11px] leading-none text-ink/35 sm:block">Press Enter to search · server-side</p>
          </div>
        </div>

        {/* Global summary strip (accurate) */}
        {overview && (
          <div className="grid gap-2.5 sm:grid-cols-3">
            {[
              { label: "Verified accounts", value: `${pct(overview.users_verified, overview.users_total)}%`, sub: `${overview.users_verified.toLocaleString()} of ${overview.users_total.toLocaleString()}`, color: "bg-emerald-500" },
              { label: "Connected listings", value: `${pct(overview.connections, overview.users_total)}%`, sub: `${overview.connections.toLocaleString()} listings · last sync ${fmtRelative(overview.last_synced_at)}`, color: "bg-sky-500" },
              { label: "New in 7 days", value: `+${overview.signups_last_7d.toLocaleString()}`, sub: `${pct(overview.signups_last_7d, overview.users_total)}% of base`, color: "bg-violet-500" },
            ].map((c) => (
              <div key={c.label} className="rounded-[6px] border-2 border-white bg-white/80 px-4 py-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{c.label}</p>
                <p className="mt-1 flex items-center gap-2 text-[14px] font-bold text-ink">
                  <span className={`h-2 w-2 rounded-full ${c.color}`} aria-hidden />
                  {c.value}
                </p>
                <p className="mt-0.5 truncate text-[11px] text-ink/45" title={c.sub}>{c.sub}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Toolbar: filters + sort */}
      <div className="flex flex-col gap-3 rounded-[6px] border-2 border-white bg-white/70 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              { key: "all", label: "All", count: filterCounts.all },
              { key: "verified", label: "Verified", count: filterCounts.verified },
              { key: "unverified", label: "Unverified", count: filterCounts.unverified },
              { key: "connected", label: "Connected", count: filterCounts.connected },
              { key: "not_connected", label: "Not connected", count: filterCounts.not_connected },
            ] as const
          ).map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              aria-pressed={filter === f.key}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-semibold transition ${
                filter === f.key ? "bg-deep-violet text-white shadow-sm" : "bg-white text-ink/60 ring-1 ring-ink/[0.06] hover:bg-ink/[0.03] hover:text-ink"
              }`}
            >
              {f.label} <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${filter === f.key ? "bg-white/20 text-white" : "bg-ink/[0.06] text-ink/50"}`}>{f.count}</span>
            </button>
          ))}
          {hasActiveFilter && (
            <button onClick={() => setFilter("all")} className="ml-1 text-[11px] font-semibold text-deep-violet hover:underline">
              Clear
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <label className="text-[11px] font-semibold text-ink/40">Sort</label>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="rounded-xl border border-ink/[0.08] bg-white px-2.5 py-1.5 text-[12px] font-semibold text-ink outline-none focus:border-deep-violet/30"
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="reviews">Most reviews</option>
            <option value="posts">Most posts</option>
          </select>
          <span className="hidden text-[11px] text-ink/30 sm:inline">·</span>
          <span className="text-[11px] text-ink/40">
            {loading ? "Loading…" : hasActiveFilter ? `${visible.length} of ${items.length} on page` : `${visible.length} on page`}
          </span>
        </div>
      </div>

      {/* Error */}
      {error ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
          <button onClick={() => setPage((p) => p)} className="btn-primary mt-3">
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-hidden rounded-[6px] border-2 border-white bg-white/80 shadow-sm md:block">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]">
                <thead>
                  <tr className="border-b border-ink/[0.06] bg-ink/[0.02] text-[11px] uppercase tracking-wide text-ink/40">
                    <th className="px-4 py-3 font-bold">Tenant</th>
                    <th className="px-4 py-3 font-bold">Listing & sync</th>
                    <th className="px-4 py-3 text-center font-bold">Content</th>
                    <th className="px-4 py-3 text-right font-bold">Joined</th>
                    <th className="px-3 py-3 text-right font-bold" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/[0.04]">
                  {loading ? (
                    Array.from({ length: pageSize === 10 ? 5 : 6 }).map((_, i) => (
                      <tr key={i}>
                        <td colSpan={5} className="px-4 py-4">
                          <div className="flex items-center gap-3">
                            <div className="h-9 w-9 animate-pulse rounded-full bg-ink/[0.06]" />
                            <div className="flex-1 space-y-2">
                              <div className="h-3 w-40 animate-pulse rounded bg-ink/[0.06]" />
                              <div className="h-2 w-56 animate-pulse rounded bg-ink/[0.04]" />
                            </div>
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : visible.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-14 text-center">
                        <div className="mx-auto max-w-[420px]">
                          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-ink/[0.05] text-ink/30">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
                              <path d="M15.5 15.5L19 19" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                            </svg>
                          </div>
                          <p className="mt-3 text-[13px] font-semibold text-ink">No tenants match</p>
                          <p className="mt-1 text-[12px] leading-relaxed text-ink/45">
                            {search ? `No match for “${search}”. Try a broader email or name.` : hasActiveFilter ? "No one matches this filter on the current page. Clear filters or go to next page." : "No tenants found."}
                          </p>
                          {(search || hasActiveFilter) && (
                            <div className="mt-3 flex justify-center gap-2">
                              {search && (
                                <button onClick={() => setSearchInput("")} className="btn-secondary !px-3 !py-1.5">
                                  Clear search
                                </button>
                              )}
                              {hasActiveFilter && (
                                <button onClick={() => setFilter("all")} className="btn-primary !px-3 !py-1.5">
                                  Show all
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    visible.map((t) => {
                      const name = [t.first_name, t.last_name].filter(Boolean).join(" ");
                      return (
                        <tr key={t.id} className="group transition hover:bg-deep-violet/[0.03]">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <div className="relative shrink-0">
                                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet ring-1 ring-deep-violet/10">
                                  {initials(t)}
                                </div>
                                <span
                                  className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${t.email_verified ? "bg-emerald-500" : "bg-amber-400"}`}
                                  title={t.email_verified ? "Verified" : "Unverified"}
                                  aria-hidden
                                />
                              </div>
                              <div className="min-w-0">
                                <Link href={`/tenants/${t.id}`} className="block truncate text-[13px] font-semibold leading-none text-ink hover:text-deep-violet hover:underline" title={t.email}>
                                  {t.email}
                                </Link>
                                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] leading-none">
                                  <span className="truncate text-ink/60">{name || "— no name —"}</span>
                                  <span className="text-ink/20">·</span>
                                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${t.email_verified ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"}`}>
                                    {t.email_verified ? "Verified" : "Unverified"}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            {t.has_connection ? (
                              <div className="min-w-0">
                                <p className="flex items-center gap-1.5 truncate text-[12px] font-semibold text-ink" title={t.listing_name ?? ""}>
                                  <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" aria-hidden />
                                  <span className="truncate">{t.listing_name ?? "Connected listing"}</span>
                                </p>
                                <p className="mt-0.5 truncate text-[11px] text-ink/45" title={t.last_synced_at ? new Date(t.last_synced_at).toLocaleString() : ""}>
                                  Synced {fmtRelative(t.last_synced_at)} · {t.last_synced_at ? fmtDate(t.last_synced_at) : "never"}
                                </p>
                              </div>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-semibold text-ink/50">
                                <span className="h-2 w-2 rounded-full bg-ink/20" aria-hidden /> Not connected
                              </span>
                            )}
                          </td>

                          <td className="px-4 py-3">
                            <div className="flex items-center justify-center gap-1.5">
                              <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-1 text-[11px] font-bold tabular-nums text-sky-700 ring-1 ring-sky-100" title="Reviews">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden className="opacity-60">
                                  <path d="M12 3.5l2 4 4.5.7-3.2 3.1.8 4.4L12 13.7 7.9 15.7l.8-4.4L5.5 8.2l4.5-.7 2-4z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                                </svg>
                                {t.reviews}
                              </span>
                              <span className="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-1 text-[11px] font-bold tabular-nums text-violet-700 ring-1 ring-violet-100" title="Posts">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden className="opacity-60">
                                  <rect x="4" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeWidth="1.4" />
                                  <path d="M8 9h8M8 12h6M8 15h8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                                </svg>
                                {t.posts}
                              </span>
                              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-1 text-[11px] font-bold tabular-nums text-amber-700 ring-1 ring-amber-100" title="Databanks">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden className="opacity-60">
                                  <ellipse cx="12" cy="7" rx="7" ry="3.5" stroke="currentColor" strokeWidth="1.4" />
                                  <path d="M5 7v8c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5V7" stroke="currentColor" strokeWidth="1.4" />
                                  <path d="M5 12c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5" stroke="currentColor" strokeWidth="1.4" />
                                </svg>
                                {t.databanks}
                              </span>
                            </div>
                          </td>

                          <td className="px-4 py-3 text-right">
                            <p className="text-[12px] font-medium tabular-nums text-ink/70" title={t.created_at ? new Date(t.created_at).toLocaleString() : ""}>
                              {fmtDate(t.created_at)}
                            </p>
                            <p className="text-[11px] text-ink/40">{fmtRelative(t.created_at)}</p>
                          </td>

                          <td className="px-3 py-3 text-right">
                            <Link
                              href={`/tenants/${t.id}`}
                              className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-white text-ink/40 ring-1 ring-ink/[0.06] transition group-hover:bg-deep-violet group-hover:text-white group-hover:ring-deep-violet"
                              aria-label={`View ${t.email}`}
                              title="View details"
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                                <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </Link>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Mobile cards */}
          <div className="grid gap-3 md:hidden">
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="animate-pulse rounded-[6px] border-2 border-white bg-white/60 p-4">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-full bg-ink/[0.06]" />
                    <div className="flex-1 space-y-2">
                      <div className="h-3 w-36 rounded bg-ink/[0.06]" />
                      <div className="h-2 w-48 rounded bg-ink/[0.04]" />
                    </div>
                  </div>
                </div>
              ))
            ) : visible.length === 0 ? (
              <div className="rounded-[6px] border-2 border-white bg-white/80 p-8 text-center">
                <p className="text-[13px] font-semibold text-ink">No tenants match</p>
                <p className="mt-1 text-[12px] text-ink/45">{search ? `No match for “${search}”.` : "Try clearing filters."}</p>
                {(search || hasActiveFilter) && (
                  <button onClick={() => { setSearchInput(""); setFilter("all"); }} className="btn-primary mt-3">
                    Clear
                  </button>
                )}
              </div>
            ) : (
              visible.map((t) => {
                const name = [t.first_name, t.last_name].filter(Boolean).join(" ");
                return (
                  <Link
                    key={t.id}
                    href={`/tenants/${t.id}`}
                    className="rounded-[6px] border-2 border-white bg-white/80 p-4 shadow-sm transition hover:shadow-md"
                  >
                    <div className="flex items-start gap-3">
                      <div className="relative shrink-0">
                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-deep-violet/10 text-[12px] font-bold text-deep-violet">{initials(t)}</div>
                        <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${t.email_verified ? "bg-emerald-500" : "bg-amber-400"}`} aria-hidden />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-semibold text-ink">{t.email}</p>
                        <p className="truncate text-[11px] text-ink/50">{name || "— no name —"} · {t.email_verified ? "Verified" : "Unverified"}</p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {t.has_connection ? (
                            <span className="inline-flex max-w-full items-center gap-1.5 truncate rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-100">
                              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden /> {t.listing_name ?? "Connected"}
                            </span>
                          ) : (
                            <span className="rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-semibold text-ink/50">Not connected</span>
                          )}
                          <span className="rounded-full bg-white px-2 py-1 text-[11px] font-medium tabular-nums text-ink/60 ring-1 ring-ink/[0.06]">{fmtRelative(t.created_at)} · {fmtDate(t.created_at)}</span>
                        </div>
                        <div className="mt-3 flex items-center gap-1.5">
                          <span className="rounded-full bg-sky-50 px-2 py-1 text-[11px] font-bold tabular-nums text-sky-700 ring-1 ring-sky-100">{t.reviews} reviews</span>
                          <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-bold tabular-nums text-violet-700 ring-1 ring-violet-100">{t.posts} posts</span>
                          <span className="rounded-full bg-amber-50 px-2 py-1 text-[11px] font-bold tabular-nums text-amber-700 ring-1 ring-amber-100">{t.databanks} banks</span>
                        </div>
                      </div>
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-ink/[0.04] text-ink/30">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                          <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                    </div>
                  </Link>
                );
              })
            )}
          </div>
        </>
      )}

      {/* Pagination */}
      <div className="flex flex-col gap-3 rounded-[6px] border-2 border-white bg-white/60 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink/50">
          <span className="font-medium tabular-nums text-ink/60">
            {total === 0 ? "No results" : `${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${total.toLocaleString()}`}
            {search ? ` for “${search}”` : ""}
            {hasActiveFilter ? ` · ${visible.length} shown after filter` : ""}
          </span>
          <span className="hidden text-ink/20 sm:inline">·</span>
          <label className="inline-flex items-center gap-1.5">
            <span className="hidden sm:inline">Rows</span> per page
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(0);
              }}
              className="rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink outline-none"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || loading}
            className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.03] disabled:opacity-40"
          >
            Prev
          </button>
          <div className="flex items-center gap-1">
            {Array.from({ length: pages }).slice(0, pages > 7 ? 7 : pages).map((_, i) => {
              // simple window around current page
              let idx = i;
              if (pages > 7) {
                if (page < 3) idx = i;
                else if (page > pages - 4) idx = pages - 7 + i;
                else idx = page - 3 + i;
              }
              const isActive = idx === page;
              return (
                <button
                  key={idx}
                  onClick={() => setPage(idx)}
                  aria-current={isActive ? "page" : undefined}
                  className={`h-8 w-8 rounded-xl text-[12px] font-bold transition ${isActive ? "bg-deep-violet text-white shadow-sm" : "bg-white text-ink/60 ring-1 ring-ink/[0.06] hover:bg-ink/[0.03]"}`}
                >
                  {idx + 1}
                </button>
              );
            })}
            {pages > 7 && <span className="px-1 text-[11px] text-ink/30">…</span>}
            {pages > 7 && (
              <span className="hidden text-[11px] text-ink/30 sm:inline">of {pages}</span>
            )}
          </div>
          <button
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            disabled={page >= pages - 1 || loading}
            className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.03] disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>

      <p className="pb-1 text-center text-[11px] text-ink/30">Tip: filters refine the current page; search queries the whole tenant base. Open a tenant to see recent reviews & posts.</p>
    </div>
  );
}
