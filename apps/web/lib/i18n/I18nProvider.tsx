"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api-rag";
import ar from "./ar";
import en, { type Dict } from "./en";
import {
  DEFAULT_LOCALE,
  isLocaleCode,
  loadLocale,
  localeDir,
  saveLocale,
  type LocaleCode,
} from "./locales";

const DICTS: Record<LocaleCode, Dict> = {
  en,
  ar,
  // es/fr/de/ur fall back to English until their dictionaries land.
  es: en,
  fr: en,
  de: en,
  ur: en,
};

interface I18nContextValue {
  locale: LocaleCode;
  dir: "ltr" | "rtl";
  t: Dict;
  setLocale: (code: LocaleCode) => void;
}

const I18nContext = createContext<I18nContextValue>({
  locale: DEFAULT_LOCALE,
  dir: "ltr",
  t: en,
  setLocale: () => {},
});

export function useI18n() {
  return useContext(I18nContext);
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [locale, setLocaleState] = useState<LocaleCode>(() => loadLocale() ?? DEFAULT_LOCALE);

  // Adopt the profile language on first sign-in when no local choice exists yet.
  useEffect(() => {
    if (!user) return;
    try {
      if (window.localStorage.getItem("sayvors.locale")) return;
    } catch {
      return;
    }
    if (isLocaleCode(user.language ?? "") && user.language !== DEFAULT_LOCALE) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time adoption of server preference
      setLocaleState(user.language as LocaleCode);
      saveLocale(user.language as LocaleCode);
    }
  }, [user]);

  // Keep <html> dir/lang in sync (drives RTL layout + screen readers).
  useEffect(() => {
    document.documentElement.dir = localeDir(locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback(
    (code: LocaleCode) => {
      setLocaleState((prev) => {
        if (prev === code) return prev;
        saveLocale(code);
        // Persist to profile so it follows the user across devices.
        // Theme is required by the endpoint — read what ThemeProvider stored.
        let theme = "light";
        try {
          theme = window.localStorage.getItem("sayvors-theme") === "dark" ? "dark" : "light";
        } catch {
          /* keep default */
        }
        apiFetch("/api/v1/profile/preferences", {
          method: "PATCH",
          body: JSON.stringify({ theme, language: code }),
        }).catch(() => {
          /* offline/backend down — local choice still applies */
        });
        return code;
      });
    },
    []
  );

  const value = useMemo<I18nContextValue>(
    () => ({ locale, dir: localeDir(locale), t: DICTS[locale], setLocale }),
    [locale, setLocale]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
