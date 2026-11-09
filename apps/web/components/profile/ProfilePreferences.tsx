"use client";

import { useState } from "react";
import { LOCALES } from "@/lib/i18n/locales";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type ProfileDict = Dict["profile"];

const THEME_IDS = ["light", "dark", "system"] as const;
type ThemeId = (typeof THEME_IDS)[number];

const CARD =
  "rounded-[32px] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)] ring-1 ring-ink/[0.06] dark:bg-[#1b1530] dark:ring-white/[0.08] sm:p-7";

function ThemePreview({ theme }: { theme: ThemeId }) {
  if (theme === "system") {
    // Two solid halves read as "follows the device" without a gradient.
    return (
      <span className="flex h-9 w-14 overflow-hidden rounded-[10px] ring-1 ring-ink/10 dark:ring-white/15">
        <span className="h-full w-1/2 bg-white" />
        <span className="h-full w-1/2 bg-ink" />
      </span>
    );
  }
  return (
    <span
      className={`relative flex h-9 w-14 items-end overflow-hidden rounded-[10px] p-1.5 ring-1 ${
        theme === "light"
          ? "bg-white ring-ink/10"
          : "bg-ink ring-white/15"
      }`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-6 rounded-full ${theme === "light" ? "bg-deep-violet" : "bg-violet-light"}`}
      />
    </span>
  );
}

export default function ProfilePreferences({
  theme,
  language,
  saving,
  onSave,
}: {
  theme: string;
  language: string;
  saving: boolean;
  onSave: (theme: string, language: string) => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const pf: ProfileDict = t.profile;
  const THEMES: { id: ThemeId; label: string; hint: string }[] = [
    { id: "light", label: pf.themeLight, hint: pf.themeLightHint },
    { id: "dark", label: pf.themeDark, hint: pf.themeDarkHint },
    { id: "system", label: pf.themeSystem, hint: pf.themeSystemHint },
  ];

  async function pick(nextTheme: string, nextLang: string) {
    if (nextTheme === theme && nextLang === language) return;
    setError(null);
    try {
      await onSave(nextTheme, nextLang);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : pf.prefsSaveFail);
    }
  }

  return (
    <section aria-labelledby="preferences-title" className={CARD}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="preferences-title" className="text-[17px] font-black tracking-tight text-ink dark:text-fog">
            {pf.prefTitle}
          </h2>
          <p className="mt-0.5 text-[11.5px] text-ink/50 dark:text-fog/50">
            {pf.prefSub}
          </p>
        </div>
        {saving && (
          <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold text-ink/45 dark:text-fog/45">
            <span
              aria-hidden
              className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/25 border-t-deep-violet"
            />
            {pf.saving}
          </span>
        )}
      </div>

      <fieldset className="mt-5">
        <legend className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">
          {pf.themeLabel}
        </legend>
        <div className="mt-2.5 grid grid-cols-3 gap-2.5" role="group" aria-label={pf.themeLabel}>
          {THEMES.map((option) => {
            const active = theme === option.id;
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={active}
                disabled={saving}
                onClick={() => void pick(option.id, language)}
                className={`flex flex-col items-center gap-2 rounded-[24px] border-2 px-2 py-3 transition focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 active:translate-y-0.5 active:scale-[0.98] disabled:opacity-60 ${
                  active
                    ? "border-deep-violet bg-deep-violet/[0.04]"
                    : "border-ink/[0.08] hover:border-ink/20 dark:border-white/[0.09] dark:hover:border-white/25"
                }`}
              >
                <ThemePreview theme={option.id} />
                <span className="text-[11.5px] font-bold text-ink dark:text-fog">{option.label}</span>
                <span className="text-[9.5px] leading-none text-ink/40 dark:text-fog/40">{option.hint}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="mt-5">
        <label
          htmlFor="profile-lang"
          className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40"
        >
          {pf.langLabel}
        </label>
        <select
          id="profile-lang"
          value={language}
          disabled={saving}
          onChange={(e) => void pick(theme, e.target.value)}
          className="mt-2 w-full rounded-[20px] border border-ink/[0.12] bg-white px-4 py-3 text-[13.5px] text-ink outline-none transition focus:border-deep-violet/50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 disabled:opacity-60 dark:border-white/[0.12] dark:bg-white/[0.04] dark:text-fog"
        >
          {LOCALES.map((locale) => (
            <option key={locale.code} value={locale.code}>
              {locale.label}
            </option>
          ))}
        </select>
        <p className="mt-1.5 text-[10.5px] text-ink/40 dark:text-fog/40">
          {pf.langHint}
        </p>
      </div>

      {error && (
        <p role="alert" className="mt-3 text-[11.5px] font-semibold text-coral">
          {error}
        </p>
      )}
    </section>
  );
}
