"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { quickLinksGroup, type AdminSearchItem } from "@/lib/search-api";
import { loadRecentSearches, rememberSearch } from "@/lib/search-recent";
import { useAdminSearch } from "@/lib/use-admin-search";
import { SearchIcon } from "./SearchIcon";
import { SearchResults, searchOptionId } from "./SearchResults";

export function AdminSearch({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [recent, setRecent] = useState<string[]>(() => loadRecentSearches());
  const { groups, loading, error, preview } = useAdminSearch(query);

  const trimmed = query.trim();
  const isNarrow = trimmed.length < 2;
  const limit = isNarrow ? 6 : 5;
  const displayGroups = useMemo(
    () => (isNarrow ? [quickLinksGroup()] : groups),
    [isNarrow, groups],
  );
  const flatOptions = useMemo(
    () =>
      displayGroups.flatMap((group) =>
        group.items.slice(0, limit).map((item, index) => ({
          item,
          id: searchOptionId(group.key, index),
        })),
      ),
    [displayGroups, limit],
  );
  const boundedIndex = Math.min(activeIndex, flatOptions.length - 1);
  const active = boundedIndex >= 0 ? flatOptions[boundedIndex] : undefined;

  useEffect(() => {
    previousFocus.current = document.activeElement as HTMLElement | null;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => {
      window.clearTimeout(timer);
      previousFocus.current?.focus?.();
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const go = (item: AdminSearchItem) => {
    rememberSearch(trimmed);
    onClose();
    router.push(item.href);
  };

  const onPanelKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusables = Array.from(
      panel.querySelectorAll<HTMLElement>(
        'input, button:not([disabled]), a[href]',
      ),
    ).filter((element) => element.tabIndex !== -1);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) =>
        Math.min(index + 1, flatOptions.length - 1),
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(-1, index - 1));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (active) {
        go(active.item);
      } else if (trimmed.length >= 2) {
        rememberSearch(trimmed);
        onClose();
        router.push(`/search?q=${encodeURIComponent(trimmed)}`);
      }
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[8vh] sm:pt-[12vh]">
      <button
        type="button"
        tabIndex={-1}
        aria-label="Close search"
        onClick={onClose}
        className="absolute inset-0 bg-[var(--ui-scrim)]"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Admin search"
        onKeyDown={onPanelKeyDown}
        className="relative flex max-h-[82vh] w-full max-w-[720px] flex-col overflow-hidden rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface-solid)]"
      >
        <div className="flex items-center gap-3 border-b border-[var(--ui-line)] px-4">
          <SearchIcon className="h-4 w-4 shrink-0 text-ink/35" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(-1);
            }}
            onKeyDown={onInputKeyDown}
            placeholder="Search tenants, operators, models, jobs, audit…"
            aria-label="Search admin console"
            role="combobox"
            aria-expanded="true"
            aria-controls="admin-search-results"
            aria-autocomplete="list"
            aria-activedescendant={active?.id}
            className="h-14 min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink/30"
          />
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-[2px] border border-[var(--ui-line)] px-2 py-1 text-[10px] font-semibold text-ink/40 transition hover:border-[var(--ui-line-strong)] hover:text-ink/70"
          >
            Esc
          </button>
        </div>

        {preview ? (
          <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-[11px] text-amber-700">
            Preview data — the admin search API is not connected yet.
          </p>
        ) : null}
        {error ? (
          <p
            role="alert"
            className="border-b border-red-200 bg-red-50 px-4 py-2 text-[11px] text-red-700"
          >
            {error}
          </p>
        ) : null}

        <div className="min-h-[140px] flex-1 overflow-y-auto p-2">
          {isNarrow ? (
            <>
              {recent.length > 0 ? (
                <div className="px-3 pb-2 pt-1">
                  <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-ink/40">
                    Recent
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {recent.map((value) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => {
                          setQuery(value);
                          inputRef.current?.focus();
                        }}
                        className="rounded-full border border-[var(--ui-line)] px-2.5 py-1 text-[10.5px] font-medium text-ink/50 transition hover:border-[var(--ui-line-strong)] hover:text-ink"
                      >
                        {value}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              <div id="admin-search-results" role="listbox">
                <SearchResults
                  groups={displayGroups}
                  limit={limit}
                  activeId={active?.id}
                  onHover={(id) => {
                    const index = flatOptions.findIndex((option) => option.id === id);
                    if (index >= 0) setActiveIndex(index);
                  }}
                  onSelect={() => {
                    rememberSearch(trimmed);
                    onClose();
                  }}
                />
              </div>
              <p className="px-3 pb-2 pt-1 text-[10.5px] leading-relaxed text-ink/30">
                Try a tenant email, tenant ID, model ID, job type, or audit action.
              </p>
            </>
          ) : loading && groups.length === 0 ? (
            <div className="space-y-1.5 px-2 py-2" aria-hidden>
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-11 animate-pulse rounded-[2px] bg-ink/[0.04]" />
              ))}
            </div>
          ) : !loading && groups.length === 0 && !error ? (
            <div className="px-4 py-10 text-center">
              <p className="text-[13px] font-semibold text-ink/60">
                No matches for “{trimmed}”
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-ink/35">
                Try an email, tenant ID, model, job type, or menu name.
              </p>
            </div>
          ) : (
            <div id="admin-search-results" role="listbox">
              <SearchResults
                groups={displayGroups}
                limit={limit}
                activeId={active?.id}
                onHover={(id) => {
                  const index = flatOptions.findIndex((option) => option.id === id);
                  if (index >= 0) setActiveIndex(index);
                }}
                onSelect={() => {
                  rememberSearch(trimmed);
                  onClose();
                }}
              />
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-[var(--ui-line)] px-4 py-2 text-[10px] text-ink/35">
          <span>↑↓ navigate · ↵ open · esc close</span>
          {trimmed.length >= 2 ? (
            <Link
              href={`/search?q=${encodeURIComponent(trimmed)}`}
              onClick={() => {
                rememberSearch(trimmed);
                onClose();
              }}
              className="font-semibold text-ink/55 transition hover:text-ink"
            >
              View all results
            </Link>
          ) : (
            <span>Search across the console</span>
          )}
        </div>
      </div>
    </div>
  );
}
