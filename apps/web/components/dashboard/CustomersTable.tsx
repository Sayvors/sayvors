"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { leadCategoryLabelKnown } from "@/lib/lead-labels";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import CustomerAvatar from "@/components/customers/CustomerAvatar";
import {
  fetchCustomers,
  type Customer,
} from "@/lib/api-customers";
import { fetchCustomerProfile } from "@/lib/api-customers";
import CustomerProfileComponent from "./CustomerProfile";

const EMPTY_CUSTOMERS: Customer[] = [];

/*
 * Customers — every person we have ever had contact with, in one table.
 *
 * A customer is a thread (one person on one channel), so the table reuses
 * the inbox's grouping and augments it with lead + Google review data.
 * Clicking a row opens a side panel with the complete profile.
 */
const PRIORITY_CHIP: Record<string, string> = {
  urgent: "bg-[#FF4F6E]/10 text-[#C4304B]",
  high: "bg-amber-500/10 text-amber-700",
  normal: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  low: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

function isGoogle(platform: string | null): boolean {
  return platform === "google_reviews" || platform === "google";
}

/**
 * The second line under a customer's name. Google reviewers are keyed by an
 * internal digest, which must never be shown as contact information; their
 * location is the meaningful identifier instead.
 */
function contactLine(c: Customer, googleLabel: string, noDetails: string): string {
  if (isGoogle(c.platform)) return c.channel_name ?? googleLabel;
  if (c.username) return `@${c.username}`;
  if (!c.contact_phone) return noDetails;
  return c.contact_phone.startsWith("+") ? c.contact_phone : `+${c.contact_phone}`;
}

function shortDate(iso: string | null, locale: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(locale === "ar" ? "ar-SA" : "en-US", { month: "short", day: "numeric" });
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

export default function CustomersTable() {
  const { t, locale } = useI18n();
  const u = t.dashboard.customers;
  const catLabel = (value: string | null | undefined): string => {
    if (!value) return "—";
    const lead = leadCategoryLabelKnown(value, locale);
    if (lead) return lead;
    return (u.threadCats as Record<string, string>)[value] ?? value;
  };
  const prioLabel = (value: string | null | undefined): string => {
    if (!value) return "—";
    return (u.priorities as Record<string, string>)[value] ?? value;
  };
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [platform, setPlatform] = useState("all");
  const [category, setCategory] = useState("all");
  const [priority, setPriority] = useState("all");
  const [importantOnly, setImportantOnly] = useState(false);
  const [sort, setSort] = useState<"recent" | "important" | "messages">("important");
  const [selected, setSelected] = useState<Customer | null>(null);
  const pageKey = `${search.trim()}|${platform}|${category}|${priority}|${importantOnly}|${sort}`;
  const [extraPage, setExtraPage] = useState<{
    key: string;
    rows: Customer[];
    cursor: string | null;
    loaded: boolean;
  }>({ key: "", rows: [], cursor: null, loaded: false });
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  const customersQuery = useQuery({
    queryKey: queryKeys.customers.list(search.trim(), platform, category, priority, importantOnly, sort),
    queryFn: async () => {
      const data = await fetchCustomers({
        search: search.trim() || undefined,
        platform,
        category,
        priority,
        important: importantOnly,
        limit: 200,
        sort,
      });
      return data;
    },
    staleTime: 30 * 1000,
  });

  const activeExtra = extraPage.key === pageKey ? extraPage : null;
  const nextCursor = activeExtra?.loaded
    ? activeExtra.cursor
    : (customersQuery.data?.next_cursor ?? null);
  const customers = useMemo(
    () => [
      ...(customersQuery.data?.customers ?? EMPTY_CUSTOMERS),
      ...(activeExtra?.rows ?? []),
    ],
    [customersQuery.data, activeExtra],
  );
  const total = customersQuery.data?.total ?? 0;
  const loading = customersQuery.isPending;
  const error = customersQuery.isError
    ? customersQuery.error instanceof Error
      ? customersQuery.error.message
      : u.loadFailed
    : null;

  const profileQuery = useQuery({
    queryKey: queryKeys.customers.profile(selected?.channel_id ?? "", selected?.key ?? ""),
    queryFn: () => fetchCustomerProfile(selected!.channel_id, selected!.key),
    enabled: !!selected,
    staleTime: 60 * 1000,
  });
  const profile = selected ? (profileQuery.data ?? null) : null;
  const profileLoading = selected ? profileQuery.isPending : false;

  const visible = useMemo(() => {
    const rows = [...customers];
    if (sort === "important") {
      rows.sort((a, b) => (a.important ? 0 : 1) - (b.important ? 0 : 1) || (new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime()));
    } else if (sort === "messages") {
      rows.sort((a, b) => b.message_count - a.message_count);
    } else {
      rows.sort((a, b) => new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime());
    }
    return rows;
  }, [customers, sort]);

  const platforms = useMemo(() => {
    const set = new Set<string>();
    for (const c of customers) if (c.platform) set.add(c.platform);
    return [...set];
  }, [customers]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const c of customers) if (c.category) set.add(c.category);
    return [...set];
  }, [customers]);

  const importantTotal = customers.filter((c) => c.important).length;

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const page = await fetchCustomers({
        search: search.trim() || undefined,
        platform,
        category,
        priority,
        important: importantOnly,
        limit: 200,
        sort,
        cursor: nextCursor,
      });
      setExtraPage((prev) => {
        const current = prev.key === pageKey ? prev.rows : [];
        const seen = new Set(
          current.map((c) => `${c.channel_id}:${c.key}`),
        );
        const base = new Set(
          (customersQuery.data?.customers ?? []).map(
            (c) => `${c.channel_id}:${c.key}`,
          ),
        );
        return {
          key: pageKey,
          rows: [
            ...current,
            ...page.customers.filter(
              (c) =>
                !seen.has(`${c.channel_id}:${c.key}`) &&
                !base.has(`${c.channel_id}:${c.key}`),
            ),
          ],
          cursor: page.next_cursor,
          loaded: true,
        };
      });
    } catch (e) {
      setLoadMoreError(
        e instanceof Error ? e.message : u.loadMoreFailed,
      );
    } finally {
      setLoadingMore(false);
    }
  };

  const filterSelect =
    "h-9 w-full rounded-lg border border-ink/[0.08] bg-white px-2 text-[11px] font-semibold text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog sm:w-auto";

  return (
    <div className="flex h-full min-h-0 gap-0 xl:gap-4">
      <div
        className={`${
          selected ? "hidden xl:flex" : "flex"
        } min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink`}
      >
        {/* Filters */}
        <div className="border-b border-ink/[0.06] p-3 dark:border-fog/[0.06]">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={u.searchPh}
            aria-label={u.searchAria}
            enterKeyHint="search"
            className="input-field h-9 w-full text-[12px] sm:text-[13px]"
          />
          <div className="mt-2 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              aria-label={u.filterPlatform}
              className={filterSelect}
            >
              <option value="all">{u.allPlatforms}</option>
              {platforms.map((p) => (
                <option key={p} value={p}>
                  {platformLabel(p)}
                </option>
              ))}
            </select>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label={u.filterCategory}
              className={filterSelect}
            >
              <option value="all">{u.allCategories}</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              aria-label={u.filterPriority}
              className={filterSelect}
            >
              <option value="all">{u.allPriority}</option>
              <option value="urgent">{u.priorities.urgent}</option>
              <option value="high">{u.priorities.high}</option>
              <option value="normal">{u.priorities.normal}</option>
              <option value="low">{u.priorities.low}</option>
            </select>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "recent" | "important" | "messages")}
              aria-label={u.sortAria}
              className={`${filterSelect} sm:ml-auto`}
            >
              <option value="important">{u.sortImportant}</option>
              <option value="recent">{u.sortRecent}</option>
              <option value="messages">{u.sortMessages}</option>
            </select>
            <button
              onClick={() => setImportantOnly((v) => !v)}
              aria-pressed={importantOnly}
              className={`col-span-2 flex h-9 items-center justify-center gap-1.5 rounded-lg border text-[11px] font-semibold transition sm:col-span-1 sm:w-auto sm:px-2.5 ${
                importantOnly
                  ? "border-[#FF4F6E]/30 bg-[#FF4F6E]/10 text-[#C4304B]"
                  : "border-ink/[0.08] text-ink/55 hover:text-ink/80 dark:border-fog/[0.1] dark:text-fog/55 dark:hover:text-fog/80"
              }`}
            >
              {importantOnly && (
                <span className="h-1.5 w-1.5 rounded-full bg-[#C4304B]" aria-hidden />
              )}
              {u.important}{importantTotal ? ` (${importantTotal})` : ""}
            </button>
          </div>
        </div>

        {/* Customers */}
        <div className="min-h-0 flex-1 overflow-auto">
          {loading && customers.length === 0 ? (
            <div className="flex justify-center py-16">
              <span className="text-[12px] text-ink/40">{u.loading}</span>
            </div>
          ) : visible.length === 0 ? (
            <p className="px-4 py-10 text-center text-[12px] text-ink/40">
              {search ? u.emptySearch : u.emptyNone}
            </p>
          ) : (
            <>
              {/* Phones: identity, platform and state on one card; the table
                  below is too wide to read without horizontal scrolling. */}
              <div className="divide-y divide-ink/[0.05] dark:divide-fog/[0.05] sm:hidden">
                {visible.map((c) => (
                  <button
                    key={`${c.channel_id}:${c.key}`}
                    type="button"
                    onClick={() => setSelected(c)}
                    className="flex w-full items-start gap-3 px-3 py-3 text-left transition hover:bg-ink/[0.02] active:bg-ink/[0.04] dark:hover:bg-fog/[0.03] dark:active:bg-fog/[0.05]"
                  >
                    <CustomerAvatar name={c.display_name} url={c.avatar_url} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[14px] font-semibold text-ink dark:text-fog">
                          {c.display_name || u.unknownSender}
                        </span>
                        {c.unread > 0 && (
                          <span className="ml-auto rounded-full bg-deep-violet px-1.5 py-0.5 text-[10px] font-bold text-white">
                            {c.unread}
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 flex min-w-0 items-center gap-1 text-[11px] text-ink/45 dark:text-fog/45">
                        <PlatformMark platform={c.platform as never} size={14} />
                        <span className="shrink-0">{platformLabel(c.platform ?? "")}</span>
                        <span className="truncate">· {contactLine(c, u.googleReview, u.noDetails)}</span>
                      </span>
                      <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        {c.category && c.category !== "normal" && (
                          <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-semibold text-[var(--ui-ink)]">
                            {catLabel(c.category)}
                          </span>
                        )}
                        {c.priority && c.priority !== "normal" && (
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${PRIORITY_CHIP[c.priority] ?? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                            {prioLabel(c.priority)}
                          </span>
                        )}
                        {c.important && (
                          <span className="rounded-full bg-[#FF4F6E]/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#C4304B]">
                            {u.important}
                          </span>
                        )}
                        <span className="ml-auto text-[10px] tabular-nums text-ink/35 dark:text-fog/35">
                          {shortDate(c.last_message_at, locale)}
                        </span>
                      </span>
                    </span>
                    <svg
                      viewBox="0 0 24 24"
                      className="mt-1 h-4 w-4 shrink-0 text-ink/25 dark:text-fog/25"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      aria-hidden
                    >
                      <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                ))}
              </div>

              <table className="hidden w-full table-fixed text-left text-[12px] sm:table">
                <thead className="sticky top-0 bg-[var(--ui-sunken)] text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                  <tr>
                    <th className="w-[40%] px-3 py-2 2xl:w-[30%]">{u.colName}</th>
                    <th className="w-[18%] px-3 py-2 2xl:w-[12%]">{u.colPlatform}</th>
                    <th className="hidden w-[18%] px-3 py-2 2xl:table-cell">{u.colChannel}</th>
                    <th className="w-[14%] px-3 py-2 2xl:w-[10%]">{u.colCategory}</th>
                    <th className="w-[14%] px-3 py-2 2xl:w-[10%]">{u.colPriority}</th>
                    <th className="hidden w-[8%] px-3 py-2 text-right 2xl:table-cell">{u.colMsgs}</th>
                    <th className="w-[14%] px-3 py-2 text-center 2xl:w-[12%]">{u.colInbox}</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((c) => (
                    <tr
                      key={`${c.channel_id}:${c.key}`}
                      onClick={() => setSelected(c)}
                      className={`cursor-pointer border-b border-ink/[0.04] transition hover:bg-ink/[0.02] dark:border-fog/[0.04] dark:hover:bg-fog/[0.03] ${
                        selected?.channel_id === c.channel_id && selected?.key === c.key ? "bg-deep-violet/[0.06]" : ""
                      }`}
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <CustomerAvatar name={c.display_name} url={c.avatar_url} size="sm" />
                          <span className="min-w-0">
                            <span className="block truncate font-semibold text-ink dark:text-fog">
                              {c.display_name || u.unknownSender}
                              {c.unread > 0 && (
                                <span className="ml-1.5 inline-block rounded-full bg-deep-violet px-1.5 text-[9px] font-bold leading-4 text-white">
                                  {c.unread}
                                </span>
                              )}
                              {c.important && (
                                <span className="ml-1.5 inline-block rounded-full bg-[#FF4F6E]/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[#C4304B]">
                                  {u.important}
                                </span>
                              )}
                            </span>
                            <span className="block truncate text-[10px] text-ink/40 dark:text-fog/40">
                              {contactLine(c, u.googleReview, u.noDetails)}
                              {c.last_message_at ? ` · ${shortDate(c.last_message_at, locale)}` : ""}
                            </span>
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center gap-1.5 text-ink/60 dark:text-fog/60">
                          <PlatformMark platform={c.platform as never} size={14} />
                          <span>{platformLabel(c.platform ?? "")}</span>
                        </span>
                      </td>
                      <td className="hidden px-3 py-2 text-ink/60 dark:text-fog/60 2xl:table-cell">{c.channel_name || "—"}</td>
                      <td className="px-3 py-2 text-ink/60 dark:text-fog/60">{c.category ? catLabel(c.category) : "—"}</td>
                      <td className="px-3 py-2">
                        {c.priority ? (
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${PRIORITY_CHIP[c.priority] ?? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                            {prioLabel(c.priority)}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="hidden px-3 py-2 text-right text-ink/60 dark:text-fog/60 2xl:table-cell">{c.message_count}</td>
                      <td className="px-3 py-2 text-center">
                        <Link
                          href={`/dashboard/channels/inbox?channel=${encodeURIComponent(c.channel_id)}&key=${encodeURIComponent(c.key)}`}
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-1 rounded-md border border-ink/[0.08] bg-white px-2 py-1 text-[10px] font-semibold text-deep-violet transition hover:bg-deep-violet/5 dark:border-fog/[0.1] dark:bg-ink dark:hover:bg-deep-violet/10"
                        >
                          {u.open}
                          <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M4 2h6v6M10 2L4 8" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
        {loadMoreError && (
          <p
            role="alert"
            className="px-4 py-2 text-[12px] font-medium text-red-600 dark:text-red-400"
          >
            {loadMoreError}
          </p>
        )}
        {nextCursor && (
          <div className="border-t border-ink/[0.06] p-2 text-center dark:border-fog/[0.06]">
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={loadingMore}
              className="rounded-full border border-ink/[0.08] bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/60 dark:hover:text-fog"
            >
              {loadingMore ? u.loading : u.loadMore}
            </button>
          </div>
        )}
        {error && (
          <p className="px-4 py-2 text-[12px] font-medium text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
        <div className="border-t border-ink/[0.06] px-4 py-2 text-[11px] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
          {fill(u.count, { count: total })}
        </div>
      </div>

      {/* Profile — full screen on phones, side panel from lg up. */}
      {selected && (
        <aside className="flex w-full min-w-0 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink xl:w-[400px] xl:shrink-0">
          <div className="flex items-center gap-2 border-b border-ink/[0.06] px-2.5 py-2 dark:border-fog/[0.06] sm:px-3">
            <button
              type="button"
              onClick={() => setSelected(null)}
              aria-label={u.backTo}
              className="flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] font-semibold text-deep-violet transition hover:bg-deep-violet/5 xl:hidden"
            >
              ← {t.common.back}
            </button>
            <p className="hidden flex-1 truncate text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40 xl:block">
              {u.profileTitle}
            </p>
            <div className="flex-1 xl:hidden" />
            <Link
              href={
                isGoogle(selected.platform)
                  ? "/dashboard/reviews"
                  : `/dashboard/channels/inbox?channel=${encodeURIComponent(selected.channel_id)}&key=${encodeURIComponent(selected.key)}`
              }
              className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-deep-violet px-2.5 py-1.5 text-[11px] font-bold text-white transition hover:bg-deep-violet/90"
            >
              <span className="xl:hidden">{isGoogle(selected.platform) ? u.reviews : u.inbox}</span>
              <span className="hidden xl:inline">{isGoogle(selected.platform) ? u.openReviews : u.openInboxPanel}</span>
              <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M4 2h6v6M10 2L4 8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Link>
            <button
              type="button"
              onClick={() => setSelected(null)}
              aria-label={u.closeProfile}
              className="hidden h-8 w-8 items-center justify-center rounded-full text-[16px] font-bold text-ink/45 hover:bg-ink/[0.04] dark:text-fog/45 dark:hover:bg-fog/[0.06] xl:flex"
            >
              ×
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
            {profileLoading && !profile ? (
              <div className="space-y-3" aria-label="Loading profile">
                <div className="h-16 w-16 animate-pulse rounded-full bg-[var(--ui-sunken)]" />
                <div className="h-5 w-40 animate-pulse rounded bg-[var(--ui-sunken)]" />
                <div className="h-20 animate-pulse rounded-xl bg-[var(--ui-sunken)]" />
              </div>
            ) : profile ? (
              <CustomerProfileComponent
                key={`${selected.channel_id}:${selected.key}`}
                profile={profile}
                selected={selected}
                onCategoryChanged={() => void queryClient.invalidateQueries({ queryKey: ["customers"] })}
              />
            ) : (
              <div className="px-1 py-6 text-center">
                <p className="text-[12px] text-ink/45 dark:text-fog/45">
                  {profileQuery.isError ? u.profileError : u.profileNone}
                </p>
                {profileQuery.isError && (
                  <button
                    type="button"
                    onClick={() => void profileQuery.refetch()}
                    className="mt-3 rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white"
                  >
                    {u.tryAgain}
                  </button>
                )}
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

// CustomerProfile is imported above and used in the side panel.