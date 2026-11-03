"use client";

import Link from "next/link";
import { startTransition, useEffect, useMemo, useState } from "react";
import { SearchIcon } from "@/components/SearchIcon";
import { SearchResults } from "@/components/SearchResults";
import { SEARCH_SCOPE } from "@/lib/search-api";
import { loadRecentSearches, rememberSearch } from "@/lib/search-recent";
import { useAdminSearch } from "@/lib/use-admin-search";

const POPULAR = ["tenant@example.com", "groq", "Pro", "review.sync", "admin"];

export default function AdminSearchPage() {
  const [query, setQuery] = useState("");
  const [recent, setRecent] = useState<string[]>([]);
  const { groups, loading, error, preview } = useAdminSearch(query);
  const trimmed = query.trim();
  const total = useMemo(
    () => groups.reduce((sum, group) => sum + group.items.length, 0),
    [groups],
  );

  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("q") ?? "";
    const saved = loadRecentSearches();
    // Browser-only state; defer it so the server-rendered empty shell hydrates
    // first and the local history/URL fill in without a mismatched render.
    startTransition(() => {
      if (initial) setQuery(initial);
      setRecent(saved);
    });
  }, []);

  const change = (value: string) => {
    setQuery(value);
    const url = new URL(window.location.href);
    if (value.trim()) url.searchParams.set("q", value.trim());
    else url.searchParams.delete("q");
    window.history.replaceState(null, "", url.toString());
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setRecent(rememberSearch(query));
  };

  const applySearch = (value: string) => {
    change(value);
    setRecent(rememberSearch(value));
  };

  return (
    <div className="mx-auto max-w-[980px] space-y-6">
      <header className="admin-rise text-center">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink/40">
          Sayvors · Admin
        </p>
        <h1 className="mt-1.5 text-[26px] font-bold tracking-tight text-ink">
          Search
        </h1>
        <p className="mx-auto mt-2 max-w-[620px] text-[14px] font-medium leading-relaxed text-ink sm:text-[15px]">
          Find a tenant, operator, model, plan, price, job, audit entry, or
          destination. Read-only and admin-scoped.
        </p>
      </header>

      <form
        onSubmit={submit}
        role="search"
        className="mx-auto flex w-full max-w-[760px] items-center gap-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-1.5"
      >
        <SearchIcon className="h-4 w-4 shrink-0 text-ink/35" />
        <input
          autoFocus
          value={query}
          onChange={(event) => change(event.target.value)}
          placeholder="Search tenants, operators, models, plans, jobs, audit…"
          aria-label="Search admin console"
          className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink/30"
        />
        {query ? (
          <button
            type="button"
            onClick={() => change("")}
            className="shrink-0 rounded-[2px] border border-[var(--ui-line)] px-2 py-1 text-[10px] font-semibold text-ink/40 transition hover:border-[var(--ui-line-strong)] hover:text-ink/70"
          >
            Clear
          </button>
        ) : (
          <span className="hidden shrink-0 rounded-[2px] border border-[var(--ui-line)] px-1.5 py-0.5 text-[9px] font-semibold text-ink/30 sm:inline">
            Ctrl K
          </span>
        )}
      </form>

      {preview ? (
        <p className="mx-auto max-w-[760px] rounded-[2px] border border-amber-200 bg-amber-50 px-3 py-2 text-center text-[11px] text-amber-700">
          Preview data — the admin search API is not connected yet. These are
          local examples used to review the layout.
        </p>
      ) : null}
      {error ? (
        <p
          role="alert"
          className="mx-auto max-w-[760px] rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-center text-[11px] leading-relaxed text-red-700"
        >
          {error}
        </p>
      ) : null}

      {trimmed.length < 2 ? (
        <div className="mx-auto max-w-[720px] space-y-7">
          <div className="flex flex-wrap items-center justify-center gap-2">
            <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-ink/35">
              Try
            </span>
            {POPULAR.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => applySearch(value)}
                className="rounded-full border border-[var(--ui-line)] px-2.5 py-1 text-[10.5px] font-medium text-ink/50 transition hover:border-[var(--ui-line-strong)] hover:text-ink"
              >
                {value}
              </button>
            ))}
          </div>

          <div className="text-center">
            <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-ink/35">
              Recent searches
            </p>
            {recent.length > 0 ? (
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                {recent.map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => applySearch(value)}
                    className="rounded-[2px] border border-[var(--ui-line)] px-2.5 py-1.5 text-[11px] font-medium text-ink/55 transition hover:border-[var(--ui-line-strong)] hover:text-ink"
                  >
                    {value}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-1.5 text-[11.5px] text-ink/35">
                No recent searches yet.
              </p>
            )}
          </div>

          <div>
            <p className="text-center text-[9px] font-bold uppercase tracking-[0.16em] text-ink/35">
              Search across
            </p>
            <div className="mt-3 border-t border-[var(--ui-line)]">
              {SEARCH_SCOPE.map((item, index) => (
                <Link
                  key={item.label}
                  href={item.href}
                  className="group grid grid-cols-[2rem_1fr_auto] items-baseline gap-x-4 gap-y-1 border-b border-[var(--ui-line)] py-3 transition hover:bg-ink/[0.02] sm:grid-cols-[2.5rem_10rem_1fr_auto] sm:px-2"
                >
                  <span className="text-[10px] font-semibold tabular-nums text-ink/25">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="text-[12.5px] font-semibold text-ink transition group-hover:text-deep-violet">
                    {item.label}
                  </span>
                  <span className="col-start-2 text-[11px] leading-relaxed text-ink/40 sm:col-start-3 sm:row-start-1">
                    {item.desc}
                  </span>
                  <svg
                    aria-hidden
                    viewBox="0 0 24 24"
                    fill="none"
                    className="col-start-3 row-start-1 h-3.5 w-3.5 self-center text-ink/20 opacity-0 transition group-hover:opacity-100 sm:col-start-4"
                  >
                    <path
                      d="M9 5l7 7-7 7"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </Link>
              ))}
            </div>
          </div>

          <p className="text-center text-[11px] leading-relaxed text-ink/35">
            Type at least 2 characters to search records. Menu destinations are
            available immediately with Ctrl/Cmd + K.
          </p>
        </div>
      ) : (
        <div className="mx-auto w-full max-w-[860px] space-y-3">
          {loading && groups.length === 0 ? (
            <div className="space-y-2" aria-hidden>
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div
                  key={i}
                  className="h-11 animate-pulse rounded-[2px] bg-ink/[0.04]"
                />
              ))}
            </div>
          ) : !loading && groups.length === 0 && !error ? (
            <div className="px-4 py-12 text-center">
              <p className="text-[14px] font-semibold text-ink/65">
                No matches for “{trimmed}”
              </p>
              <p className="mx-auto mt-1 max-w-[420px] text-[11.5px] leading-relaxed text-ink/40">
                Try an email address, tenant ID, model ID, job type, plan name,
                or audit action.
              </p>
            </div>
          ) : groups.length > 0 ? (
            <section className="panel p-3" aria-label="Search results">
              <div className="flex items-baseline justify-between gap-3 px-2 pb-2">
                <p className="text-[11px] font-medium text-ink/45">
                  {total} result{total === 1 ? "" : "s"} for “{trimmed}”
                </p>
                <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-ink/30">
                  Read-only
                </span>
              </div>
              <SearchResults
                groups={groups}
                onSelect={() => setRecent(rememberSearch(trimmed))}
              />
            </section>
          ) : null}
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-ink/25">
        Admin search is metadata-only. Message bodies, review text and secrets
        are not included.
      </p>
    </div>
  );
}
