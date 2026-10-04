"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { adminFetch, type AdminOverview, type AdminTenant } from "@/lib/admin-api";

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;
const DEFAULT_SIZE = 25;
const QUIET_AFTER_MS = 7 * 86400 * 1000;

type FilterKey = "all" | "verified" | "unverified" | "connected" | "not_connected";
type SortKey = "newest" | "oldest" | "reviews" | "posts" | "attention";

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

// ─── funnel stage: where this tenant is stuck ─────────────────────────────
type Stage = "unverified" | "unconnected" | "quiet" | "active";
const STAGE_RANK: Record<Stage, number> = { unverified: 0, unconnected: 1, quiet: 2, active: 3 };
const STAGE_META: Record<Stage, { label: string; pill: string; dot: string }> = {
  unverified: {
    label: "Unverified",
    pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
    dot: "bg-amber-400",
  },
  unconnected: {
    label: "Not connected",
    pill: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
    dot: "bg-sky-500",
  },
  quiet: {
    label: "Quiet 7d+",
    pill: "bg-ink/[0.05] text-ink/55 ring-1 ring-ink/[0.08]",
    dot: "bg-ink/25",
  },
  active: {
    label: "Active",
    pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    dot: "bg-emerald-500",
  },
};

function stageOf(t: AdminTenant): Stage {
  if (!t.email_verified) return "unverified";
  if (!t.has_connection) return "unconnected";
  if (!t.last_synced_at) return "quiet";
  const stale = Date.now() - new Date(t.last_synced_at).getTime() > QUIET_AFTER_MS;
  return stale ? "quiet" : "active";
}

function nudgeLine(t: AdminTenant, stage: Stage): string {
  switch (stage) {
    case "unverified":
      return `joined ${fmtRelative(t.created_at)} · awaiting verification`;
    case "unconnected":
      return "verified · no listing connected yet";
    case "quiet":
      return t.last_synced_at ? `last sync ${fmtRelative(t.last_synced_at)}` : "never synced — check the listing";
    case "active":
      return `${t.reviews} reviews · ${t.posts} posts · synced ${fmtRelative(t.last_synced_at)}`;
  }
}

const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

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
  const [reloadKey, setReloadKey] = useState(0);
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // overview for accurate global stats (promise callbacks only)
  useEffect(() => {
    adminFetch<AdminOverview>("/api/v1/admin/overview").then(setOverview).catch(() => {});
  }, []);

  // debounce the server-side search; timer callback, never sync in the body
  useEffect(() => {
    if (searchInput.trim() === search) return;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      setLoading(true);
      setSearch(searchInput.trim());
      setPage(0);
    }, 350);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [searchInput, search]);

  // tenant list fetch: no synchronous setState in the effect body
  useEffect(() => {
    let cancelled = false;
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
  }, [search, page, pageSize, reloadKey]);

  const gotoPage = (p: number) => {
    setLoading(true);
    setPage(p);
  };

  const pages = Math.max(1, Math.ceil(total / pageSize));
  const rangeStart = total === 0 ? 0 : page * pageSize + 1;
  const rangeEnd = Math.min(total, (page + 1) * pageSize);

  // client filter/sort for the current page (server search stays authoritative)
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
      case "attention":
        out.sort(
          (a, b) =>
            STAGE_RANK[stageOf(a)] - STAGE_RANK[stageOf(b)] ||
            (a.created_at ?? "").localeCompare(b.created_at ?? ""),
        );
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

  // lede facts from accurate global stats
  const base = overview?.users_total || 0;
  const verifiedN = overview?.users_verified || 0;
  const connectedN = overview?.connections || 0;
  const neverVerified = Math.max(0, base - verifiedN);
  const neverConnected = Math.max(0, verifiedN - connectedN);

  return (
    <div className="space-y-4">
      {/* ── masthead ─────────────────────────────────────────── */}
      <div className="admin-rise flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink/40">
            Sayvors · Admin
          </p>
          <h1 className="mt-1 text-[22px] font-bold tracking-tight text-ink">Tenants</h1>
          <p className="mt-1.5 max-w-[680px] text-[14px] font-medium leading-relaxed text-ink sm:text-[15px]">
            {overview ? (
              <>
                <b className="font-bold text-deep-violet">{base.toLocaleString()} tenants</b> ·{" "}
                {pct(verifiedN, base)}% verified · {pct(connectedN, base)}% connected
                {neverVerified > 0 && (
                  <>
                    {" — "}
                    <b className="font-bold text-amber-600">{neverVerified} never verified</b>
                  </>
                )}
                {neverVerified === 0 && neverConnected > 0 && (
                  <>
                    {" — "}
                    <b className="font-bold text-sky-700">{neverConnected} verified but unconnected</b>
                  </>
                )}
                {neverVerified === 0 && neverConnected === 0 && base > 0 && (
                  <span className="text-ink/60"> — everybody is through the funnel.</span>
                )}
              </>
            ) : (
              "Every account that signed up — who is stuck, and what they need next."
            )}
          </p>
        </div>
        <div className="relative w-full shrink-0 lg:w-[320px]">
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
            className={`w-full rounded-xl border border-ink/[0.08] bg-white py-2.5 pl-9 pr-9 text-[13px] text-ink placeholder:text-ink/35 outline-none transition focus:border-deep-violet/30 focus:ring-4 focus:ring-deep-violet/10 ${FOCUS_RING}`}
          />
          {searchInput && (
            <button
              type="button"
              onClick={() => setSearchInput("")}
              aria-label="Clear search"
              className={`absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1.5 text-ink/30 transition hover:bg-ink/[0.06] hover:text-ink ${FOCUS_RING}`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M7 7l10 10M17 7L7 17" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* ── ruled funnel strip ───────────────────────────────── */}
      {overview && (
        <section
          aria-label="Tenant funnel totals"
          className="admin-rise rounded-[6px] border-2 border-white bg-white/80 px-5 py-4"
          style={{ animationDelay: "70ms" }}
        >
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4 sm:divide-x sm:divide-ink/[0.07]">
            {[
              { label: "Total tenants", value: base.toLocaleString(), note: `+${overview.signups_last_7d.toLocaleString()} in 7 days` },
              { label: "Verified", value: `${pct(verifiedN, base)}%`, note: `${verifiedN.toLocaleString()} accounts` },
              { label: "Connected", value: `${pct(connectedN, base)}%`, note: `${connectedN.toLocaleString()} listings` },
              {
                label: "Stuck in funnel",
                value: (neverVerified + neverConnected).toLocaleString(),
                note: neverVerified + neverConnected > 0 ? "need a nudge ↓" : "funnel is clear",
                alert: neverVerified + neverConnected > 0,
              },
            ].map((s, i) => (
              <div key={s.label} className={i > 0 ? "sm:pl-6" : ""}>
                <dt className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">{s.label}</dt>
                <dd className={`mt-0.5 text-[26px] font-bold tabular-nums leading-none ${s.alert ? "text-amber-600" : "text-ink"}`}>
                  {s.value}
                </dd>
                <dd className="mt-1 text-[11px] text-ink/45">{s.note}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {/* ── toolbar: filters + sort ──────────────────────────── */}
      <div
        className="admin-rise flex flex-col gap-3 rounded-[6px] border-2 border-white bg-white/70 p-3 sm:flex-row sm:items-center sm:justify-between"
        style={{ animationDelay: "140ms" }}
      >
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter tenants">
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
                filter === f.key
                  ? "bg-deep-violet text-white shadow-sm"
                  : "bg-white text-ink/60 ring-1 ring-ink/[0.06] hover:bg-ink/[0.03] hover:text-ink"
              } ${FOCUS_RING}`}
            >
              {f.label}{" "}
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${filter === f.key ? "bg-white/20 text-white" : "bg-ink/[0.06] text-ink/50"}`}
              >
                {f.count}
              </span>
            </button>
          ))}
          {hasActiveFilter && (
            <button onClick={() => setFilter("all")} className={`ml-1 text-[11px] font-semibold text-deep-violet hover:underline ${FOCUS_RING}`}>
              Clear
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="tenant-sort" className="text-[11px] font-semibold text-ink/40">
            Sort
          </label>
          <select
            id="tenant-sort"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className={`rounded-xl border border-ink/[0.08] bg-white px-2.5 py-1.5 text-[12px] font-semibold text-ink outline-none focus:border-deep-violet/30 ${FOCUS_RING}`}
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="attention">Needs attention</option>
            <option value="reviews">Most reviews</option>
            <option value="posts">Most posts</option>
          </select>
          <span className="text-[11px] tabular-nums text-ink/40" aria-live="polite">
            {loading ? "Loading…" : hasActiveFilter ? `${visible.length} of ${items.length} on page` : `${visible.length} on page`}
          </span>
        </div>
      </div>

      {/* ── error ────────────────────────────────────────────── */}
      {error ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
          <button
            onClick={() => {
              setLoading(true);
              setError(null);
              setReloadKey((k) => k + 1);
            }}
            className={`btn-primary mt-3 ${FOCUS_RING}`}
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* ── desktop ledger ─────────────────────────────── */}
          <div
            className="admin-rise hidden overflow-hidden rounded-[6px] border-2 border-white bg-white/80 shadow-sm md:block"
            style={{ animationDelay: "210ms" }}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]">
                <thead>
                  <tr className="border-b border-ink/[0.08] text-[10px] uppercase tracking-[0.12em] text-ink/40">
                    <th scope="col" className="px-4 py-3 font-bold">Tenant</th>
                    <th scope="col" className="px-4 py-3 font-bold">Listing & sync</th>
                    <th scope="col" className="px-4 py-3 text-right font-bold">Reviews</th>
                    <th scope="col" className="px-4 py-3 text-right font-bold">Posts</th>
                    <th scope="col" className="px-4 py-3 text-right font-bold">Banks</th>
                    <th scope="col" className="px-4 py-3 text-right font-bold">Joined</th>
                    <th scope="col" className="px-3 py-3 text-right font-bold">
                      <span className="sr-only">Open tenant</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/[0.05]">
                  {loading ? (
                    Array.from({ length: 6 }).map((_, i) => (
                      <tr key={i}>
                        <td colSpan={7} className="px-4 py-4">
                          <div className="flex items-center gap-3" aria-hidden>
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
                      <td colSpan={7} className="px-4 py-14 text-center">
                        <p className="text-[13px] font-semibold text-ink">No tenants match</p>
                        <p className="mx-auto mt-1 max-w-[420px] text-[12px] leading-relaxed text-ink/45">
                          {search
                            ? `No match for “${search}”. Try a broader email or name.`
                            : hasActiveFilter
                              ? "Nobody matches this filter on the current page — clear it or turn the page."
                              : "No tenants found."}
                        </p>
                        {(search || hasActiveFilter) && (
                          <div className="mt-3 flex justify-center gap-2">
                            {search && (
                              <button onClick={() => setSearchInput("")} className={`btn-secondary !px-3 !py-1.5 ${FOCUS_RING}`}>
                                Clear search
                              </button>
                            )}
                            {hasActiveFilter && (
                              <button onClick={() => setFilter("all")} className={`btn-primary !px-3 !py-1.5 ${FOCUS_RING}`}>
                                Show all
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ) : (
                    visible.map((t) => {
                      const name = [t.first_name, t.last_name].filter(Boolean).join(" ");
                      const stage = stageOf(t);
                      const meta = STAGE_META[stage];
                      return (
                        <tr key={t.id} className="group transition hover:bg-deep-violet/[0.03]">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <div className="relative shrink-0" aria-hidden>
                                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet ring-1 ring-deep-violet/10">
                                  {initials(t)}
                                </div>
                                <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${meta.dot}`} />
                              </div>
                              <div className="min-w-0">
                                <Link
                                  href={`/tenants/${t.id}`}
                                  className={`block truncate text-[13px] font-semibold leading-none text-ink hover:text-deep-violet hover:underline ${FOCUS_RING} rounded`}
                                  title={t.email}
                                >
                                  {t.email}
                                </Link>
                                <p className="mt-1 truncate text-[11px] leading-none text-ink/45">
                                  {name ? `${name} · ` : ""}
                                  {nudgeLine(t, stage)}
                                </p>
                                <span
                                  className={`mt-1.5 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${meta.pill}`}
                                >
                                  {meta.label}
                                </span>
                              </div>
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            {t.has_connection ? (
                              <div className="min-w-0">
                                <p className="truncate text-[12px] font-semibold text-ink" title={t.listing_name ?? ""}>
                                  {t.listing_name ?? "Connected listing"}
                                </p>
                                <p
                                  className="mt-0.5 truncate text-[11px] text-ink/45"
                                  title={t.last_synced_at ? new Date(t.last_synced_at).toLocaleString() : ""}
                                >
                                  Synced {fmtRelative(t.last_synced_at)}
                                </p>
                              </div>
                            ) : (
                              <span className="text-[12px] font-medium text-ink/40">— no listing —</span>
                            )}
                          </td>

                          <td className="px-4 py-3 text-right text-[13px] font-bold tabular-nums text-ink">{t.reviews}</td>
                          <td className="px-4 py-3 text-right text-[13px] font-bold tabular-nums text-ink">{t.posts}</td>
                          <td className="px-4 py-3 text-right text-[13px] font-bold tabular-nums text-ink">{t.databanks}</td>

                          <td className="px-4 py-3 text-right">
                            <p
                              className="text-[12px] font-medium tabular-nums text-ink/70"
                              title={t.created_at ? new Date(t.created_at).toLocaleString() : ""}
                            >
                              {fmtDate(t.created_at)}
                            </p>
                            <p className="text-[11px] text-ink/40">{fmtRelative(t.created_at)}</p>
                          </td>

                          <td className="px-3 py-3 text-right">
                            <Link
                              href={`/tenants/${t.id}`}
                              className={`inline-flex h-8 w-8 items-center justify-center rounded-xl bg-white text-ink/40 ring-1 ring-ink/[0.06] transition group-hover:bg-deep-violet group-hover:text-white group-hover:ring-deep-violet ${FOCUS_RING}`}
                              aria-label={`Open ${t.email}`}
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

          {/* ── mobile cards ───────────────────────────────── */}
          <div className="admin-rise grid gap-3 md:hidden" style={{ animationDelay: "210ms" }}>
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="animate-pulse rounded-[6px] border-2 border-white bg-white/60 p-4" aria-hidden>
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
                  <button
                    onClick={() => {
                      setSearchInput("");
                      setFilter("all");
                    }}
                    className={`btn-primary mt-3 ${FOCUS_RING}`}
                  >
                    Clear
                  </button>
                )}
              </div>
            ) : (
              visible.map((t) => {
                const name = [t.first_name, t.last_name].filter(Boolean).join(" ");
                const stage = stageOf(t);
                const meta = STAGE_META[stage];
                return (
                  <Link
                    key={t.id}
                    href={`/tenants/${t.id}`}
                    aria-label={`${t.email} — ${meta.label}. ${nudgeLine(t, stage)}`}
                    className={`block rounded-[6px] border-2 border-white bg-white/80 p-4 shadow-sm transition hover:shadow-md ${FOCUS_RING}`}
                  >
                    <div className="flex items-start gap-3">
                      <div className="relative shrink-0" aria-hidden>
                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-deep-violet/10 text-[12px] font-bold text-deep-violet">
                          {initials(t)}
                        </div>
                        <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${meta.dot}`} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-semibold text-ink">{t.email}</p>
                        <p className="truncate text-[11px] text-ink/50">
                          {name ? `${name} · ` : ""}
                          {nudgeLine(t, stage)}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${meta.pill}`}>
                            {meta.label}
                          </span>
                          <span className="rounded-full bg-white px-2 py-1 text-[11px] font-bold tabular-nums text-ink/60 ring-1 ring-ink/[0.06]">
                            {t.reviews} rev · {t.posts} posts · {t.databanks} banks
                          </span>
                        </div>
                      </div>
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-ink/[0.04] text-ink/30" aria-hidden>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
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

      {/* ── pagination ─────────────────────────────────────── */}
      <div className="flex flex-col gap-3 rounded-[6px] border-2 border-white bg-white/60 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink/50">
          <span className="font-medium tabular-nums text-ink/60" aria-live="polite">
            {total === 0 ? "No results" : `${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${total.toLocaleString()}`}
            {search ? ` for “${search}”` : ""}
            {hasActiveFilter ? ` · ${visible.length} shown after filter` : ""}
          </span>
          <span className="hidden text-ink/20 sm:inline" aria-hidden>
            ·
          </span>
          <label className="inline-flex items-center gap-1.5">
            Rows per page
            <select
              value={pageSize}
              onChange={(e) => {
                setLoading(true);
                setPageSize(Number(e.target.value));
                setPage(0);
              }}
              aria-label="Rows per page"
              className={`rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink outline-none ${FOCUS_RING}`}
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        <nav aria-label="Tenant pages" className="flex items-center gap-1.5">
          <button
            onClick={() => gotoPage(Math.max(0, page - 1))}
            disabled={page === 0 || loading}
            className={`rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.03] disabled:opacity-40 ${FOCUS_RING}`}
          >
            Prev
          </button>
          <div className="flex items-center gap-1">
            {Array.from({ length: pages })
              .slice(0, pages > 7 ? 7 : pages)
              .map((_, i) => {
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
                    onClick={() => gotoPage(idx)}
                    aria-current={isActive ? "page" : undefined}
                    aria-label={`Page ${idx + 1}`}
                    className={`h-8 w-8 rounded-xl text-[12px] font-bold tabular-nums transition ${
                      isActive ? "bg-deep-violet text-white shadow-sm" : "bg-white text-ink/60 ring-1 ring-ink/[0.06] hover:bg-ink/[0.03]"
                    } ${FOCUS_RING}`}
                  >
                    {idx + 1}
                  </button>
                );
              })}
            {pages > 7 && (
              <span className="px-1 text-[11px] text-ink/30" aria-hidden>
                …
              </span>
            )}
            {pages > 7 && <span className="hidden text-[11px] tabular-nums text-ink/30 sm:inline">of {pages}</span>}
          </div>
          <button
            onClick={() => gotoPage(Math.min(pages - 1, page + 1))}
            disabled={page >= pages - 1 || loading}
            className={`rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.03] disabled:opacity-40 ${FOCUS_RING}`}
          >
            Next
          </button>
        </nav>
      </div>

      <p className="pb-1 text-center text-[11px] text-ink/30">
        Filters refine the current page · search queries the whole base · “Needs attention” surfaces stuck tenants first.
      </p>
    </div>
  );
}
