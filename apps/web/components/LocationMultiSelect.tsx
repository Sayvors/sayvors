"use client";

import { useState } from "react";

export interface MultiSelectLocation {
  id: string;
  name: string;
}

/** Checkbox dropdown: "All locations" + per-branch. Shared by Posts/Services. */
export default function LocationMultiSelect({ locations, selectedIds, onToggle, onSelectAll }: {
  locations: MultiSelectLocation[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  onSelectAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const all = locations.length > 0 && selectedIds.length === locations.length;
  const label = all
    ? `All ${locations.length} location${locations.length === 1 ? "" : "s"}`
    : selectedIds.length === 0
      ? "Select locations…"
      : selectedIds.length === 1
        ? locations.find((l) => l.id === selectedIds[0])?.name ?? "1 location"
        : `${selectedIds.length} locations`;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Choose locations"
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
          <div className="absolute z-20 mt-1 max-h-60 w-full overflow-y-auto rounded-xl border border-ink/[0.08] bg-white p-1 shadow-xl dark:border-fog/[0.12] dark:bg-ink">
            <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.05]">
              <input
                type="checkbox"
                checked={all}
                onChange={onSelectAll}
                className="h-4 w-4 shrink-0 accent-deep-violet"
              />
              <span className="text-[13px] font-semibold text-ink dark:text-fog">
                All locations{locations.length > 0 ? ` (${locations.length})` : ""}
              </span>
            </label>
            <div className="mx-2 my-1 border-t border-ink/[0.06] dark:border-fog/[0.08]" aria-hidden />
            {locations.map((l) => (
              <label key={l.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.05]">
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
              <p className="px-2.5 py-2 text-[12px] text-ink/40">No locations connected yet.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
