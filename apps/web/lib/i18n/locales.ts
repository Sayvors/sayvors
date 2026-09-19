export type LocaleCode = "en" | "es" | "fr" | "de" | "ar" | "ur";

export interface LocaleMeta {
  code: LocaleCode;
  label: string;
  flag: string;
  dir: "ltr" | "rtl";
}

/** Mirrors the header language dropdown. Arabic + Urdu are right-to-left. */
export const LOCALES: LocaleMeta[] = [
  { code: "en", label: "English", flag: "🇺🇸", dir: "ltr" },
  { code: "es", label: "Spanish", flag: "🇪🇸", dir: "ltr" },
  { code: "fr", label: "French", flag: "🇫🇷", dir: "ltr" },
  { code: "de", label: "German", flag: "🇩🇪", dir: "ltr" },
  { code: "ar", label: "Arabic", flag: "🇸🇦", dir: "rtl" },
  { code: "ur", label: "Urdu", flag: "🇵🇰", dir: "rtl" },
];

export const DEFAULT_LOCALE: LocaleCode = "en";

export function isLocaleCode(code: string): code is LocaleCode {
  return LOCALES.some((l) => l.code === code);
}

export function localeDir(code: LocaleCode): "ltr" | "rtl" {
  return LOCALES.find((l) => l.code === code)?.dir ?? "ltr";
}

const STORAGE_KEY = "sayvors.locale";

export function loadLocale(): LocaleCode | null {
  try {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw && isLocaleCode(raw) ? raw : null;
  } catch {
    return null;
  }
}

export function saveLocale(code: LocaleCode): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, code);
  } catch {
    /* storage unavailable */
  }
}
