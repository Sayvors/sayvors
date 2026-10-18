"use client";

import { INK } from "@/components/channels/instagram/ui";

/*
 * Switch shared by the unified Publish composer. Copied verbatim from the
 * channel hubs' Switch (channels/ui.tsx) so both surfaces stay identical —
 * importing that one directly would tie the composer to the hub folder.
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
      aria-label={label || undefined}
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
      {label && <span className={`text-left text-[13px] font-semibold ${INK}`}>{label}</span>}
    </button>
  );
}
