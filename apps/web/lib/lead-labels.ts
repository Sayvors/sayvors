/*
 * One lead label for every surface.
 *
 * The backend stores the category (wholesale/retail/booking/quote/support/
 * info) and is the only classifier. This map is presentation only — do not
 * invent a new label in a component, or the inbox, lead card, digest and
 * escalation email drift apart again (HAND-5).
 */

export type LeadCategory =
  | "wholesale"
  | "retail"
  | "booking"
  | "quote"
  | "support"
  | "info";

export const LEAD_CATEGORIES: LeadCategory[] = [
  "wholesale",
  "retail",
  "booking",
  "quote",
  "support",
  "info",
];

export const LEAD_CATEGORY_LABELS: Record<LeadCategory, string> = {
  wholesale: "Wholesale",
  retail: "Retail",
  booking: "Booking",
  quote: "Quote",
  support: "Support",
  info: "Info",
};

/** Display label for a stored category; null when none was captured. */
export function leadCategoryLabel(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  return LEAD_CATEGORY_LABELS[value as LeadCategory] ?? value;
}

/** Arabic labels for the same canonical catalog (MSA UI). */
export const LEAD_CATEGORY_LABELS_AR: Record<LeadCategory, string> = {
  wholesale: "البيع بالجملة",
  retail: "البيع بالتجزئة",
  booking: "حجز",
  quote: "عرض سعر",
  support: "دعم",
  info: "معلومات",
};

/**
 * Localized label for a known lead category, null when unknown (so callers
 * can fall back to thread-category labels or the raw value).
 */
export function leadCategoryLabelKnown(
  value: string | null | undefined,
  locale: string,
): string | null {
  if (!value) return null;
  const known = value as LeadCategory;
  if (!(known in LEAD_CATEGORY_LABELS)) return null;
  return locale === "ar" ? LEAD_CATEGORY_LABELS_AR[known] : LEAD_CATEGORY_LABELS[known];
}
