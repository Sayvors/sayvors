"use client";

import { INK } from "@/components/channels/instagram/ui";

/*
 * Switch shared by the unified Publish composer.
 *
 * Design rules (AGENTS.md):
 *   - Radius ≈ 25% of element height → pill (rounded-full)
 *   - 3px solid :focus-visible outline on interactive clay elements
 *   - Press feedback: translateY(2px) scale(0.98), never animate box-shadow
 *   - Surfaces are solid; depth from hairlines + shadow stack
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
      className={`flex items-center gap-3 transition-transform duration-150 active:translate-y-[2px] active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none outline-none ${
        disabled
          ? ""
          : "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] focus-visible:-outline-offset-[2px]"
      }`}
    >
      <span
        className={`relative inline-block h-6 w-10 shrink-0 rounded-full transition-colors duration-200 ${
          checked
            ? "bg-[var(--ui-ink)]"
            : "border border-[var(--ui-line)] bg-[var(--ui-surface)]"
        }`}
      >
        <span
          className={`absolute top-[2px] left-[2px] h-5 w-5 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.15)] transition-transform duration-200 ease-out ${
            checked
              ? "translate-x-[22px] shadow-[0_2px_5px_rgba(0,0,0,0.25)]"
              : "shadow-[0_1px_2px_rgba(0,0,0,0.10)]"
          }`}
        />
      </span>
      {label && (
        <span className={`text-left text-[13px] font-semibold ${INK}`}>{label}</span>
      )}
    </button>
  );
}
