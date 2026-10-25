"use client";

import type { MetaAsset } from "@/lib/api-meta";
import {
  ErrorNote,
  PrimaryButton,
  SecondaryButton,
  StepActions,
  StepHeading,
} from "./OnboardingShell";

/**
 * Shared "pick which discovered asset Sayvors should use" step.
 *
 * Meta returns every Page / Instagram account / number the token can see;
 * the tenant owns the choice, and an empty selection is meaningful (it
 * deactivates what is left out), so the save button never silently
 * re-selects everything.
 */
export default function AssetPicker({
  eyebrow = "Almost there",
  title,
  body,
  emptyText,
  assets,
  picked,
  onToggle,
  onSave,
  onBack,
  busy,
  error,
  savedLabel,
}: {
  eyebrow?: string;
  title: string;
  body: string;
  emptyText: string;
  assets: MetaAsset[];
  picked: string[];
  onToggle: (assetId: string) => void;
  onSave: () => void;
  onBack?: () => void;
  busy: boolean;
  error: string | null;
  savedLabel: string;
}) {
  return (
    <div>
      <StepHeading eyebrow={eyebrow} title={title} body={body} />

      {error && <ErrorNote>{error}</ErrorNote>}

      {assets.length === 0 ? (
        <p className="mt-4 rounded-lg bg-ink/[0.03] px-3 py-2.5 text-[12px] leading-relaxed text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">
          {emptyText}
        </p>
      ) : (
        <div className="mt-4 space-y-2">
          {assets.map((a) => {
            const checked = picked.includes(a.id);
            return (
              <label
                key={a.id}
                className="flex cursor-pointer items-center gap-3 rounded-lg border border-ink/[0.06] bg-white px-3 py-2.5 transition hover:border-deep-violet/25 dark:border-fog/[0.08] dark:bg-ink"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(a.id)}
                  className="h-4 w-4 shrink-0 accent-[#5b2d8e]"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink dark:text-fog">
                    {a.name || a.username || a.phone || a.external_asset_id}
                  </span>
                  <span className="block truncate text-[11px] text-ink/45 dark:text-fog/45">
                    {a.asset_type}
                    {a.status !== "connected" ? ` · ${a.status}` : ""}
                    {a.active ? " · currently active" : ""}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}

      <StepActions hint={savedLabel}>
        <PrimaryButton onClick={onSave} disabled={busy || assets.length === 0}>
          {busy ? "Saving…" : picked.length === 0 ? "Deselect all" : `Use selected (${picked.length})`}
        </PrimaryButton>
        {onBack && <SecondaryButton onClick={onBack} disabled={busy}>Back</SecondaryButton>}
      </StepActions>
    </div>
  );
}
