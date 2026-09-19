"use client";

const THEMES = [
  { id: "light", label: "Light", hint: "Bright workspace" },
  { id: "dark", label: "Dark", hint: "Low-light friendly" },
  { id: "system", label: "System", hint: "Follow device" },
] as const;

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "ar", label: "Arabic" },
  { code: "zh", label: "Chinese" },
  { code: "ja", label: "Japanese" },
];

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
  async function pick(nextTheme: string, nextLang: string) {
    if (nextTheme === theme && nextLang === language) return;
    await onSave(nextTheme, nextLang);
  }

  return (
    <section aria-label="Preferences" className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm">
      <div className="mb-4">
        <h3 className="text-[14px] font-bold text-ink">Preferences</h3>
        <p className="text-[11px] text-ink/45">
          Saved to your account{saving ? " · saving…" : ""}.
        </p>
      </div>

      <fieldset>
        <legend className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
          Theme
        </legend>
        <div className="mt-2 grid grid-cols-3 gap-2" role="radiogroup" aria-label="Theme">
          {THEMES.map((t) => {
            const active = theme === t.id;
            return (
              <button
                key={t.id}
                role="radio"
                aria-checked={active}
                disabled={saving}
                onClick={() => pick(t.id, language)}
                className={`flex flex-col items-center gap-1.5 rounded-xl border-2 p-3 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-60 ${
                  active
                    ? "border-deep-violet bg-deep-violet/5"
                    : "border-ink/10 hover:border-ink/25"
                }`}
              >
                <span
                  aria-hidden
                  className={`h-8 w-12 rounded-lg border ${
                    t.id === "light"
                      ? "border-ink/10 bg-white"
                      : t.id === "dark"
                        ? "border-white/10 bg-ink"
                        : "bg-gradient-to-r from-white to-ink"
                  }`}
                />
                <span className="text-[11px] font-semibold text-ink">{t.label}</span>
                <span className="text-[9px] text-ink/40">{t.hint}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="mt-5">
        <label htmlFor="profile-lang" className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
          Language
        </label>
        <select
          id="profile-lang"
          value={language}
          disabled={saving}
          onChange={(e) => pick(theme, e.target.value)}
          className="mt-2 w-full rounded-lg border border-ink/15 bg-fog/40 px-3 py-2 text-[13px] text-ink transition focus:border-deep-violet/50 focus:outline-none focus:ring-2 focus:ring-deep-violet/20 disabled:opacity-60"
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </div>
    </section>
  );
}
