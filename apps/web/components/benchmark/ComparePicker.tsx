"use client";

import { useEffect, useRef, useState } from "react";
import { subjectKey, type SavedPlace } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

/**
 * Selection model is 5 vs 1: side B holds up to five businesses, side A holds
 * exactly one. Six subjects total. The server enforces the same cap
 * (`MAX_SUBJECTS` in benchmark/compare.py) — keep the two in sync.
 */
export const MAX_COMPETITORS = 5;
export const MAX_TOTAL = 1 + MAX_COMPETITORS;

interface ChannelOption {
  id: string;
  display_name: string | null;
  platform: string;
}

interface Option {
  key: string;
  label: string;
  group: "saved" | "own";
}

export interface CompareSelection {
  main: string | null;
  competitors: string[];
}

function buildOptions(saved: SavedPlace[], own: ChannelOption[]): Option[] {
  return [
    ...saved.map((place) => ({
      key: subjectKey("saved", place.place_id),
      label: place.label || place.name || place.place_id,
      group: "saved" as const,
    })),
    ...own.map((channel) => ({
      key: subjectKey("own", channel.id),
      label: channel.display_name || "Unnamed location",
      group: "own" as const,
    })),
  ];
}

function labelOf(options: Option[], key: string): string {
  return options.find((option) => option.key === key)?.label ?? key;
}

export default function ComparePicker({
  selection,
  onChange,
  saved,
  own,
}: {
  selection: CompareSelection;
  onChange: (next: CompareSelection) => void;
  saved: SavedPlace[];
  own: ChannelOption[];
}) {
  const options = buildOptions(saved, own);
  const { main, competitors } = selection;

  function toggleMain(key: string) {
    onChange({
      main: main === key ? null : key,
      competitors: competitors.filter((item) => item !== key),
    });
  }

  function toggleCompetitor(key: string) {
    if (competitors.includes(key)) {
      onChange({ main, competitors: competitors.filter((item) => item !== key) });
      return;
    }
    if (competitors.length >= MAX_COMPETITORS) return;
    onChange({ main: main === key ? null : main, competitors: [...competitors, key] });
  }

  return (
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-start">
      <SidePicker
        label="Your business"
        hint="Pick 1"
        limit={1}
        selected={main ? [main] : []}
        blockedKeys={competitors}
        options={options}
        onToggle={toggleMain}
      />

      <div className="flex items-center justify-center sm:h-full sm:pt-7">
        <span className="rounded-full border border-[#3D1D6E]/20 bg-[#F4F2F7] px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-wide text-[#3D1D6E]">
          vs
        </span>
      </div>

      <SidePicker
        label="Competitors"
        hint={`Up to ${MAX_COMPETITORS}`}
        limit={MAX_COMPETITORS}
        selected={competitors}
        blockedKeys={main ? [main] : []}
        options={options}
        onToggle={toggleCompetitor}
      />

      <p className="text-[10px] leading-relaxed text-[#3B2D5E] sm:col-span-3">
        {MAX_COMPETITORS} businesses against 1 — six columns in the table below.
        Each dropdown lists saved businesses and your own connected locations.
      </p>
    </div>
  );
}

function SidePicker({
  label,
  hint,
  limit,
  selected,
  blockedKeys,
  options,
  onToggle,
}: {
  label: string;
  hint: string;
  limit: number;
  selected: string[];
  blockedKeys: string[];
  options: Option[];
  onToggle: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const full = selected.length >= limit;
  const trigger =
    selected.length === 0
      ? "Select a business…"
      : selected.length === 1
      ? labelOf(options, selected[0])
      : `${selected.length} selected`;

  return (
    <div ref={root} className="relative min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]">{label}</span>
        <span className="text-[10px] font-semibold text-[#8A8496]">
          {hint} · {selected.length}/{limit}
        </span>
      </div>

      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((value) => !value)}
        className={`mt-1 flex h-11 w-full items-center justify-between gap-2 rounded-[12px] border bg-white px-3 text-left text-[12px] font-semibold ${FOCUS} ${
          selected.length ? "border-[#3D1D6E]/30 text-[#14101F]" : "border-[var(--ui-line)] text-[#8A8496]"
        }`}
      >
        <span className="truncate">{trigger}</span>
        <span aria-hidden className="shrink-0 text-[10px] text-[#3B2D5E]">
          ▾
        </span>
      </button>

      {selected.length > 1 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {selected.map((key) => (
            <span
              key={key}
              className="inline-flex max-w-full items-center gap-1 rounded-[8px] border border-[#3D1D6E]/15 bg-[#F4F2F7] px-1.5 py-0.5 text-[10px] font-semibold text-[#14101F]"
            >
              <span className="truncate">{labelOf(options, key)}</span>
              <button
                type="button"
                aria-label={`Remove ${labelOf(options, key)}`}
                onClick={() => onToggle(key)}
                className={`rounded-[4px] px-0.5 leading-none text-[#3B2D5E] hover:bg-white ${FOCUS}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}

      {open ? (
        <div className="absolute left-0 right-0 top-full z-30 mt-1.5 max-h-[300px] overflow-y-auto rounded-[12px] border border-[var(--ui-line)] bg-white p-1.5 shadow-[0_6px_20px_rgba(20,16,31,0.14)]">
          {options.length === 0 ? (
            <p className="px-2 py-3 text-[11px] text-[#3B2D5E]">
              Save a business or connect a Google location first.
            </p>
          ) : (
            <>
              <OptionGroup
                title="Saved businesses"
                options={options.filter((option) => option.group === "saved")}
                selected={selected}
                blockedKeys={blockedKeys}
                full={full}
                onToggle={onToggle}
              />
              <div className="my-1 border-t border-[var(--ui-line)]" />
              <OptionGroup
                title="Our own business"
                options={options.filter((option) => option.group === "own")}
                selected={selected}
                blockedKeys={blockedKeys}
                full={full}
                onToggle={onToggle}
              />
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function OptionGroup({
  title,
  options,
  selected,
  blockedKeys,
  full,
  onToggle,
}: {
  title: string;
  options: Option[];
  selected: string[];
  blockedKeys: string[];
  full: boolean;
  onToggle: (key: string) => void;
}) {
  return (
    <div>
      <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#B0338A]">{title}</p>
      {options.length === 0 ? (
        <p className="px-2 py-1 text-[10px] text-[#8A8496]">None yet</p>
      ) : (
        options.map((option) => {
          const checked = selected.includes(option.key);
          const otherSide = blockedKeys.includes(option.key);
          const disabled = otherSide || (!checked && full);
          return (
            <label
              key={option.key}
              title={otherSide ? "Already selected on the other side" : undefined}
              className={`flex items-center gap-2 rounded-[8px] px-2 py-1.5 text-[12px] text-[#14101F] ${
                disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:bg-[#F4F2F7]"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={() => onToggle(option.key)}
                className="h-4 w-4 shrink-0 accent-[#B0338A]"
              />
              <span className="truncate">{option.label}</span>
            </label>
          );
        })
      )}
    </div>
  );
}
