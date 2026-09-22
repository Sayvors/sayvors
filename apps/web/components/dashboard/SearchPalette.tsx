"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n } from "@/lib/i18n/I18nProvider";

interface SearchEntry {
  label: string;
  hint: string;
  keywords: string;
  href: string;
  section: "pages" | "actions";
}

export default function SearchPalette({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const entries: SearchEntry[] = useMemo(
    () => [
      { label: t.nav.dashboard, hint: "", keywords: "home overview main", href: "/dashboard", section: "pages" },
      { label: t.nav.analytics, hint: "", keywords: "stats reports insights growth benchmark sentiment charts performance", href: "/dashboard/analytics", section: "pages" },
      { label: t.nav.locations, hint: "", keywords: "business profile address hours working hours open closed", href: "/dashboard/locations", section: "pages" },
      { label: t.nav.services, hint: "", keywords: "offerings menu services", href: "/dashboard/services", section: "pages" },
      { label: t.nav.media, hint: "", keywords: "photos videos pictures gallery", href: "/dashboard/media", section: "pages" },
      { label: t.nav.posts, hint: "", keywords: "posting publish post updates offers news", href: "/dashboard/posts", section: "pages" },
      { label: t.nav.reviews, hint: "", keywords: "ratings replies comments stars feedback respond", href: "/dashboard/reviews", section: "pages" },
      { label: t.nav.verification, hint: "", keywords: "verify business verification badge", href: "/dashboard/verification", section: "pages" },
      { label: t.nav.databank, hint: "", keywords: "knowledge docs documents upload brain faq", href: "/dashboard/databank", section: "pages" },
      { label: t.nav.connect, hint: "", keywords: "channels google facebook instagram connect link automations automatic replies autopilot approval queue tone model", href: "/dashboard/channels", section: "pages" },
      { label: t.nav.outbox, hint: "", keywords: "drafts approve pending failed outbox publish queue", href: "/dashboard/outbox", section: "pages" },
      { label: t.nav.usage, hint: "", keywords: "tokens billing costs limits usage", href: "/dashboard/usage", section: "pages" },
      { label: t.account.myProfile, hint: "", keywords: "account profile user personal", href: "/dashboard/profile", section: "pages" },
      { label: t.header.settings, hint: "", keywords: "settings preferences configuration", href: "/dashboard/settings", section: "pages" },
      { label: t.header.newDatabank, hint: "", keywords: "create new databank knowledge", href: "/dashboard/databank/new", section: "actions" },
      { label: t.header.newChannel, hint: "", keywords: "create connect new channel automation auto-reply", href: "/dashboard/channels", section: "actions" },
    ],
    [t]
  );

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) =>
        e.label.toLowerCase().includes(q) ||
        e.keywords.toLowerCase().includes(q) ||
        e.hint.toLowerCase().includes(q)
    );
  }, [entries, query]);

  const go = (href: string) => {
    onClose();
    router.push(href);
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.header.searchLabel}
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-deep-violet/[0.1] bg-white shadow-2xl dark:border-deep-violet/[0.15] dark:bg-ink"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-deep-violet/[0.08] px-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 shrink-0 text-ink/30 dark:text-fog/30" aria-hidden>
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, results.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                if (results[active]) go(results[active].href);
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
            placeholder={t.header.search}
            aria-label={t.header.searchLabel}
            aria-expanded
            aria-controls="search-palette-list"
            role="combobox"
            aria-autocomplete="list"
            className="h-12 w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink/30 dark:text-fog dark:placeholder:text-fog/30"
          />
          {query && (
            <button
              onClick={() => {
                setQuery("");
                setActive(0);
                inputRef.current?.focus();
              }}
              aria-label={t.common.dismiss}
              className="rounded p-1 text-ink/30 transition hover:text-ink/60 dark:text-fog/30 dark:hover:text-fog/60"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          )}
          <kbd className="hidden shrink-0 rounded border border-deep-violet/[0.1] bg-white px-1.5 py-0.5 text-[10px] font-medium text-deep-violet/50 sm:block dark:bg-ink">
            esc
          </kbd>
        </div>

        <div ref={listRef} id="search-palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-1.5">
          {results.length === 0 ? (
            <p className="px-3 py-8 text-center text-[13px] text-ink/40 dark:text-fog/40">
              No matches. Try “reviews”, “hours”, “posts”…
            </p>
          ) : (
            results.map((r, i) => (
              <button
                key={`${r.section}-${r.href}-${r.label}`}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(r.href)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left outline-none transition ${
                  i === active ? "bg-deep-violet/[0.07]" : ""
                }`}
              >
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold ${
                    r.section === "actions"
                      ? "bg-emerald/10 text-emerald-600"
                      : "bg-deep-violet/[0.07] text-deep-violet"
                  }`}
                  aria-hidden
                >
                  {r.section === "actions" ? "+" : r.label.slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink dark:text-fog">
                    {r.label}
                  </span>
                  <span className="block truncate text-[10px] capitalize text-ink/35 dark:text-fog/35">
                    {r.section}
                  </span>
                </span>
                {i === active && (
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className="h-3.5 w-3.5 shrink-0 text-deep-violet">
                    <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            ))
          )}
        </div>

        <div className="hidden items-center gap-3 border-t border-deep-violet/[0.08] px-4 py-2 text-[10px] text-ink/35 sm:flex dark:text-fog/35">
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-deep-violet/[0.1] px-1">↑↓</kbd> navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-deep-violet/[0.1] px-1">↵</kbd> open
          </span>
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-deep-violet/[0.1] px-1">esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}
