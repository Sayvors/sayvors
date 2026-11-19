"use client";

import { useEffect, useRef, useState } from "react";
import { subjectKey, type SavedPlace } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

/** Server cap lives in benchmark/compare.py; keep this in sync with it. */
export const MAX_COMPARE = 6;

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

export default function ComparePicker({
  selected,
  onChange,
  saved,
  own,
}: {
  selected: string[];
  onChange: (keys: string[]) => void;
  saved: SavedPlace[];
  own: ChannelOption[];
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  const options: Option[] = [
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
  const labelFor = (key: string) =>
    options.find((option) => option.key === key)?.label ?? key;

  function toggle(key: string) {
    if (selected.includes(key)) {
      onChange(selected.filter((item) => item !== key));
    } else if (selected.length < MAX_COMPARE) {
      onChange([...selected, key]);
    }
  }

  return (
    <div ref={root} className="relative">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className={`rounded-[16px] bg-[#3D1D6E] px-4 py-2.5 text-[12px] font-bold text-white ${FOCUS}`}
        >
          Choose businesses ({selected.length}/{MAX_COMPARE})
        </button>
        {selected.length === 0 ? (
          <span className="text-[11px] text-[#3B2D5E]">
            Pick saved competitors and/or your own branches — up to {MAX_COMPARE} in one table.
          </span>
        ) : null}
      </div>

      {selected.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {selected.map((key) => (
            <span
              key={key}
              className="inline-flex items-center gap-1 rounded-[10px] border border-[#3D1D6E]/20 bg-white px-2 py-1 text-[11px] font-semibold text-[#14101F]"
            >
              {labelFor(key)}
              <button
                type="button"
                aria-label={`Remove ${labelFor(key)} from comparison`}
                onClick={() => toggle(key)}
                className={`rounded-[6px] px-1 text-[13px] leading-none text-[#3B2D5E] hover:bg-[#F4F2F7] ${FOCUS}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}

      {open ? (
        <div className="absolute left-0 top-full z-30 mt-2 max-h-[340px] w-[320px] overflow-y-auto rounded-[16px] border border-[var(--ui-line)] bg-white p-2 shadow-[0_6px_20px_rgba(20,16,31,0.14)]">
          {options.length === 0 ? (
            <p className="px-2 py-3 text-[11px] text-[#3B2D5E]">
              Save a business or connect a Google location first.
            </p>
          ) : (
            <>
              <Group
                title="Saved businesses"
                options={options.filter((option) => option.group === "saved")}
                selected={selected}
                toggle={toggle}
              />
              <div className="my-1 border-t border-[var(--ui-line)]" />
              <Group
                title="Our own business"
                options={options.filter((option) => option.group === "own")}
                selected={selected}
                toggle={toggle}
              />
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Group({
  title,
  options,
  selected,
  toggle,
}: {
  title: string;
  options: Option[];
  selected: string[];
  toggle: (key: string) => void;
}) {
  return (
    <div>
      <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#B0338A]">
        {title}
      </p>
      {options.length === 0 ? (
        <p className="px-2 py-1 text-[10px] text-[#8A8496]">None yet</p>
      ) : (
        options.map((option) => {
          const checked = selected.includes(option.key);
          const blocked = !checked && selected.length >= MAX_COMPARE;
          return (
            <label
              key={option.key}
              className={`flex items-center gap-2 rounded-[10px] px-2 py-1.5 text-[12px] text-[#14101F] ${
                blocked ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:bg-[#F4F2F7]"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={blocked}
                onChange={() => toggle(option.key)}
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
