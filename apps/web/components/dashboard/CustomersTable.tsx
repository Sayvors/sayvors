"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import {
  fetchCustomers,
  updateCustomerCategory,
  type Customer,
  type CustomerProfile,
} from "@/lib/api-customers";
import { fetchCustomerProfile } from "@/lib/api-customers";
import CustomerProfileComponent from "./CustomerProfile";

/*
 * Customers — every person we have ever had contact with, in one table.
 *
 * A customer is a thread (one person on one channel), so the table reuses
 * the inbox's grouping and augments it with lead + Google review data.
 * Clicking a row opens a side panel with the complete profile.
 */
const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";

const PRIORITY_CHIP: Record<string, string> = {
  urgent: "bg-[#FF4F6E]/10 text-[#C4304B]",
  high: "bg-amber-500/10 text-amber-700",
  normal: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  low: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

export default function CustomersTable() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [platform, setPlatform] = useState("all");
  const [category, setCategory] = useState("all");
  const [priority, setPriority] = useState("all");
  const [importantOnly, setImportantOnly] = useState(false);
  const [sort, setSort] = useState<"recent" | "important" | "messages">("important");
  const [selected, setSelected] = useState<Customer | null>(null);
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCustomers({
        search: search.trim() || undefined,
        platform,
        category,
        priority,
        important: importantOnly,
        limit: 200,
      });
      setCustomers(data.customers);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load customers.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, platform, category, priority, importantOnly]);

  useEffect(() => {
    if (!selected) {
      setProfile(null);
      return;
    }
    setProfileLoading(true);
    void fetchCustomerProfile(selected.channel_id, selected.key)
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setProfileLoading(false));
  }, [selected]);

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

  return (
    <div className="flex h-full min-h-0 gap-4">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
        {/* Filters */}
        <div className="border-b border-ink/[0.06] p-3 dark:border-fog/[0.06]">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search customers"
            aria-label="Search customers"
            className="input-field w-full"
          />
          <div className="mt-2 flex flex-wrap items-center gap-1">
            <button
              onClick={() => setImportantOnly((v) => !v)}
              aria-pressed={importantOnly}
              className={`rounded-lg px-2 py-1 text-[11px] font-semibold transition ${
                importantOnly ? "bg-[#FF4F6E]/10 text-[#C4304B]" : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
              }`}
            >
              Important{importantTotal ? ` (${importantTotal})` : ""}
            </button>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              aria-label="Filter by platform"
              className="rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value="all">All platforms</option>
              {platforms.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Filter by category"
              className="rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value="all">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              aria-label="Filter by priority"
              className="rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value="all">All priority</option>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "recent" | "important" | "messages")}
              aria-label="Sort"
              className="ml-auto rounded-lg border border-ink/[0.08] bg-white px-2 py-1 text-[11px] font-semibold text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value="important">Important first</option>
              <option value="recent">Newest first</option>
              <option value="messages">Most messages</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="min-h-0 flex-1 overflow-auto">
          {loading && customers.length === 0 ? (
            <div className="flex justify-center py-16">
              <span className="text-[12px] text-ink/40">Loading…</span>
            </div>
          ) : visible.length === 0 ? (
            <p className="px-4 py-10 text-center text-[12px] text-ink/40">
              {search ? "No customers match that search." : "No contacts yet. Once someone messages you they appear here."}
            </p>
          ) : (
            <table className="w-full text-left text-[12px]">
              <thead className="sticky top-0 bg-[var(--ui-sunken)] text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Platform</th>
                  <th className="px-3 py-2">Channel</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">Priority</th>
                  <th className="px-3 py-2">Last contact</th>
                  <th className="px-3 py-2 text-right">Msgs</th>
                  <th className="px-3 py-2 text-right">Unread</th>
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
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[10px] font-bold text-deep-violet">
                          {(c.display_name || "?").slice(0, 2).toUpperCase()}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-semibold text-ink dark:text-fog">
                            {c.display_name || "Unknown sender"}
                            {c.important && (
                              <span className="ml-1.5 inline-block rounded-full bg-[#FF4F6E]/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[#C4304B]">
                                Important
                              </span>
                            )}
                          </span>
                          <span className="block truncate text-[10px] text-ink/40 dark:text-fog/40">
                            {c.contact_phone || "—"}
                          </span>
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <PlatformMark platform={c.platform as never} size={12} />
                    </td>
                    <td className="px-3 py-2 text-ink/60 dark:text-fog/60">{c.channel_name || "—"}</td>
                    <td className="px-3 py-2 text-ink/60 dark:text-fog/60">{c.category || "—"}</td>
                    <td className="px-3 py-2">
                      {c.priority ? (
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${PRIORITY_CHIP[c.priority] ?? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                          {c.priority}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-3 py-2 text-ink/50 dark:text-fog/50">
                      {c.last_message_at ? new Date(c.last_message_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-ink/60 dark:text-fog/60">{c.message_count}</td>
                    <td className="px-3 py-2 text-right">
                      {c.unread > 0 && (
                        <span className="rounded-full bg-deep-violet px-1.5 text-[10px] font-bold text-white">
                          {c.unread}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {error && (
          <p className="px-4 py-2 text-[12px] font-medium text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
        <div className="border-t border-ink/[0.06] px-4 py-2 text-[11px] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
          {total} customers
        </div>
      </div>

      {/* Side panel */}
      {selected && (
        <aside className="flex w-full max-w-md shrink-0 flex-col overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
          <div className="flex items-center justify-between border-b border-ink/[0.06] px-4 py-3 dark:border-fog/[0.06]">
            <h2 className="truncate text-[14px] font-bold text-ink dark:text-fog">
              {selected.display_name || "Unknown sender"}
            </h2>
            <button
              onClick={() => setSelected(null)}
              aria-label="Close profile"
              className="flex h-7 w-7 items-center justify-center rounded-full text-[14px] font-bold text-ink/45 hover:bg-ink/[0.04]"
            >
              ×
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {profileLoading && !profile ? (
              <p className="text-[12px] text-ink/40">Loading…</p>
            ) : profile ? (
              <CustomerProfileComponent profile={profile} selected={selected} onCategoryChanged={() => void load()} />
            ) : (
              <p className="text-[12px] text-ink/40">Could not load profile.</p>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

// CustomerProfile is imported above and used in the side panel.