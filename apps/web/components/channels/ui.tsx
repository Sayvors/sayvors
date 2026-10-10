"use client";

import { INK } from "./instagram/ui";

/*
 * Shared primitives for the channel hubs (Facebook + future platforms) —
 * one home so they never drift apart. Instagram keeps its own ui.tsx; this
 * Switch is copied verbatim from the IG composer so both stay identical.
 */

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 disabled:opacity-50"
    >
      <span
        className={`relative inline-block h-6 w-10 shrink-0 rounded-full ${
          checked
            ? "bg-[var(--ui-ink)]"
            : "border border-[var(--ui-line-strong)] bg-[var(--ui-sunken)]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full transition-transform ${
            checked
              ? "translate-x-[18px] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
              : "translate-x-0.5 border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
          }`}
        />
      </span>
      <span className={`text-left text-[13px] font-semibold ${INK}`}>{label}</span>
    </button>
  );
}
