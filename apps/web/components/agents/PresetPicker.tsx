"use client";

import { useState } from "react";

interface PresetPickerProps {
  label: string;
  presets: { id: string; name: string }[];
  selected: string;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
  children: React.ReactNode;
}

export default function PresetPicker({ label, presets, selected, onSelect, onCreateNew, children }: PresetPickerProps) {
  const [isOpen, setIsOpen] = useState(false);

  const selectedPreset = presets.find((p) => p.id === selected);

  return (
    <div className="space-y-2">
      <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60">{label}</label>
      <div className="relative">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="flex w-full items-center justify-between rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink transition hover:border-deep-violet/30 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:hover:border-deep-violet/30"
        >
          <span>{selectedPreset?.name || "Select a preset..."}</span>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className={`h-3.5 w-3.5 text-ink/30 transition-transform dark:text-fog/30 ${isOpen ? "rotate-180" : ""}`}>
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {isOpen && (
          <div className="absolute z-20 mt-1 w-full rounded-lg border border-ink/[0.08] bg-white shadow-lg dark:border-fog/[0.08] dark:bg-ink">
            <div className="max-h-48 overflow-y-auto p-1">
              {presets.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => { onSelect(preset.id); setIsOpen(false); }}
                  className={`flex w-full items-center rounded-md px-3 py-2 text-[12px] transition ${
                    selected === preset.id
                      ? "bg-deep-violet/[0.06] text-deep-violet"
                      : "text-ink/70 hover:bg-ink/[0.04] dark:text-fog/70 dark:hover:bg-fog/[0.04]"
                  }`}
                >
                  {preset.name}
                </button>
              ))}
            </div>
            <div className="border-t border-ink/[0.06] p-1 dark:border-fog/[0.06]">
              <button
                type="button"
                onClick={() => { onSelect("new"); onCreateNew(); setIsOpen(false); }}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-[12px] font-medium text-deep-violet transition hover:bg-deep-violet/[0.06]"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                  <path d="M8 3v10M3 8h10" strokeLinecap="round" />
                </svg>
                Create New
              </button>
            </div>
          </div>
        )}
      </div>
      {selected === "new" && <div className="mt-2">{children}</div>}
    </div>
  );
}
