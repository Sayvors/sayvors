"use client";

import Link from "next/link";
import type {
  AdminSearchGroup,
  AdminSearchItem,
  SearchGroupKey,
} from "@/lib/search-api";

export function searchOptionId(group: SearchGroupKey, index: number): string {
  return `admin-search-${group}-${index}`;
}

export function SearchResults({
  groups,
  limit,
  activeId,
  onHover,
  onSelect,
  emptyText = "No matches.",
}: {
  groups: AdminSearchGroup[];
  limit?: number;
  activeId?: string;
  onHover?: (id: string) => void;
  onSelect?: (item: AdminSearchItem) => void;
  emptyText?: string;
}) {
  if (groups.length === 0) {
    return <p className="px-3 py-8 text-center text-[12px] text-ink/40">{emptyText}</p>;
  }

  return (
    <div className="space-y-1.5">
      {groups.map((group) => {
        const items = limit ? group.items.slice(0, limit) : group.items;
        return (
          <section
            key={group.key}
            role={onHover ? "group" : undefined}
            aria-label={group.label}
          >
            <div className="flex items-baseline justify-between px-3 py-1.5">
              <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-ink/40">
                {group.label}
              </p>
              <span className="text-[10px] tabular-nums text-ink/25">
                {group.items.length}
              </span>
            </div>
            <div>
              {items.map((item, index) => {
                const id = searchOptionId(group.key, index);
                const active = activeId === id;
                return (
                  <Link
                    key={`${group.key}:${item.id}`}
                    id={id}
                    href={item.href}
                    role={onHover ? "option" : undefined}
                    aria-selected={onHover ? active : undefined}
                    onMouseEnter={() => onHover?.(id)}
                    onClick={() => onSelect?.(item)}
                    className={`flex items-center gap-3 rounded-[2px] px-3 py-2 text-left transition ${
                      active
                        ? "bg-[var(--ui-sunken)]"
                        : "hover:bg-ink/[0.04] focus-visible:bg-ink/[0.04]"
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-semibold text-ink">
                        {item.title}
                      </span>
                      {item.subtitle ? (
                        <span className="mt-0.5 block truncate text-[11px] text-ink/45">
                          {item.subtitle}
                        </span>
                      ) : null}
                    </span>
                    {item.meta ? (
                      <span className="shrink-0 rounded-full bg-ink/[0.05] px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide text-ink/45">
                        {item.meta}
                      </span>
                    ) : null}
                    <svg
                      aria-hidden
                      viewBox="0 0 24 24"
                      fill="none"
                      className="h-3.5 w-3.5 shrink-0 text-ink/25"
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
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
