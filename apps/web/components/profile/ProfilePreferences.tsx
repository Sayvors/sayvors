"use client";

import { useState } from "react";

const themes = [
  { id: "light", label: "Light", preview: "bg-white border-ink/10" },
  { id: "dark", label: "Dark", preview: "bg-ink border-fog/10" },
  { id: "system", label: "System", preview: "bg-gradient-to-r from-white to-ink border-ink/10" },
];

const languages = [
  { code: "en", label: "English" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "ar", label: "Arabic" },
  { code: "zh", label: "Chinese" },
  { code: "ja", label: "Japanese" },
];

export default function ProfilePreferences() {
  const [selectedTheme, setSelectedTheme] = useState("light");
  const [selectedLang, setSelectedLang] = useState("en");

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
      <h2 className="text-[14px] font-bold text-ink mb-4">Preferences</h2>

      {/* Theme */}
      <div className="mb-5">
        <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Theme</label>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {themes.map((theme) => (
            <button
              key={theme.id}
              onClick={() => setSelectedTheme(theme.id)}
              className={`flex flex-col items-center gap-2 rounded-xl border-2 p-3 transition ${
                selectedTheme === theme.id
                  ? "border-deep-violet bg-deep-violet/5"
                  : "border-ink/[0.06] hover:border-ink/15"
              }`}
            >
              <div className={`h-8 w-12 rounded-lg border ${theme.preview}`} />
              <span className="text-[10px] font-semibold text-ink">{theme.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Language */}
      <div>
        <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Language</label>
        <select
          value={selectedLang}
          onChange={(e) => setSelectedLang(e.target.value)}
          className="mt-2 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none"
        >
          {languages.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
