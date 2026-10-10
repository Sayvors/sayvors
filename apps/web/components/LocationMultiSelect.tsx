"use client";

import { useState } from "react";

export interface MultiSelectLocation {
  id: string;
  name: string;
}

export interface MultiSelectCopy {
  allLocations: string;
  allLocationsOne: string;
  allLocationsShort: string;
  selectLocations: string;
  oneLocation: string;
  countLocations: string;
  chooseLocations: string;
  noneConnected: string;
}

const EN_COPY: MultiSelectCopy = {
  allLocations: "All {count} locations",
  allLocationsOne: "All 1 location",
  allLocationsShort: "All locations",
  selectLocations: "Select locations…",
  oneLocation: "1 location",
  countLocations: "{count} locations",
  chooseLocations: "Choose locations",
  noneConnected: "No locations connected yet.",
};

/** Checkbox dropdown: "All locations" + per-branch. Shared by Posts/Services.
 *
 * `groups` adds one-tick shortcuts for saved location groups. Ticking a group
 * checks exactly its members rather than replacing the selection, so groups
 * compose: pick "North" then add one extra branch by hand. */
export default function LocationMultiSelect({
  locations,
  selectedIds,
  onToggle,
  onSelectAll,
  onSelectGroup,
  groups,
  groupsLabel,
  copy,
}: {
  locations: MultiSelectLocation[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  /** Ticks/un-ticks a group's members. Required when `groups` is passed. */
  onSelectGroup?: (ids: string[]) => void;
  /** Saved groups, already resolved to the IDs used in `locations`. */
  groups?: { id: string; name: string; memberIds: string[] }[];
  groupsLabel?: string;
  /** Optional — falls back to English so un-translated callers keep working. */
  copy?: MultiSelectCopy;
}) {
  const t = copy ?? EN_COPY;
  const [open, setOpen] = useState(false);
  const all = locations.length > 0 && selectedIds.length === locations.length;
  const label = all
    ? locations.length === 1
      ? t.allLocationsOne
      : t.allLocations.replace("{count}", String(locations.length))
    : selectedIds.length === 0
      ? t.selectLocations
      : selectedIds.length === 1
        ? locations.find((l) => l.id === selectedIds[0])?.name ?? t.oneLocation
        : t.countLocations.replace("{count}", String(selectedIds.length));
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={t.chooseLocations}
        className="input-field flex w-full items-center justify-between gap-2 text-left"
      >
        <span className={`truncate ${selectedIds.length === 0 ? "text-ink/30" : ""}`}>{label}</span>
        <svg className={`h-4 w-4 shrink-0 text-ink/40 transition ${open ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={(e) => {
              // preventDefault stops any ancestor <label> from forwarding
              // this click to the first checkbox (services page had that bug).
              e.preventDefault();
              setOpen(false);
            }}
            aria-hidden
          />
          <div className="absolute z-20 mt-1 max-h-60 w-full overflow-y-auto rounded-[2px] border border-ink/[0.08] bg-white p-1 shadow-xl dark:border-fog/[0.12] dark:bg-ink">
            <label className="flex cursor-pointer items-center gap-2.5 rounded-[2px] px-2.5 py-2 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.05]">
              <input
                type="checkbox"
                checked={all}
                onChange={onSelectAll}
                className="h-4 w-4 shrink-0 accent-deep-violet"
              />
              <span className="text-[13px] font-semibold text-ink dark:text-fog">
                {t.allLocationsShort}{locations.length > 0 ? ` (${locations.length})` : ""}
              </span>
            </label>
            <div className="mx-2 my-1 border-t border-ink/[0.06] dark:border-fog/[0.08]" aria-hidden />
            {groups && groups.length > 0 && onSelectGroup && (
              <>
                <p className="px-2.5 pt-1.5 text-[10px] font-bold uppercase tracking-wide text-ink/35 dark:text-fog/35">
                  {groupsLabel}
                </p>
                {groups.map((g) => {
                  const members = g.memberIds.filter((id) => locations.some((l) => l.id === id));
                  if (members.length === 0) return null;
                  const on = members.every((id) => selectedIds.includes(id));
                  return (
                    <label key={g.id} className="flex cursor-pointer items-center gap-2.5 rounded-[2px] px-2.5 py-2 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.05]">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => onSelectGroup(members)}
                        className="h-4 w-4 shrink-0 accent-deep-violet"
                      />
                      <span className="truncate text-[13px] font-semibold text-ink dark:text-fog">
                        {g.name} <span className="font-normal text-ink/40">({members.length})</span>
                      </span>
                    </label>
                  );
                })}
                <div className="mx-2 my-1 border-t border-ink/[0.06] dark:border-fog/[0.08]" aria-hidden />
              </>
            )}
            {locations.map((l) => (
              <label key={l.id} className="flex cursor-pointer items-center gap-2.5 rounded-[2px] px-2.5 py-2 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.05]">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(l.id)}
                  onChange={() => onToggle(l.id)}
                  className="h-4 w-4 shrink-0 accent-deep-violet"
                />
                <span className="truncate text-[13px] text-ink/80 dark:text-fog/80">{l.name}</span>
              </label>
            ))}
            {locations.length === 0 && (
              <p className="px-2.5 py-2 text-[12px] text-ink/40">{t.noneConnected}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
