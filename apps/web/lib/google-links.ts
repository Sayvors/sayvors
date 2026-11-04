/**
 * Build and validate the links used to prove a fact on Google.
 *
 * The rule is the same as the audit's: never invent a link. A Maps URL is
 * only produced from an identifier Google actually gave us (a Places
 * `place_id` or the listing's own `maps_url`). Everything else falls back to
 * the merchant's GBP dashboard, which is a real destination but does not
 * pretend to point at a specific listing.
 */
import { safeHref } from "./safe-url";

/** The merchant's own location manager. Used when a card aggregates branches
 * and no single listing can represent the number. */
export const GBP_DASHBOARD_URL = "https://business.google.com/locations";

const GOOGLE_HOSTS = new Set(["goo.gl", "maps.app.goo.gl"]);

function isGoogleHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  if (GOOGLE_HOSTS.has(host)) return true;
  // Only the real google.com namespace (google.com, www.google.com,
  // maps.google.com). Country TLDs are deliberately rejected: a lookalike
  // such as google.com.example can be registered by anyone, and the card can
  // always fall back to the place id or GBP dashboard.
  return host === "google.com" || host.endsWith(".google.com");
}

/**
 * Return a stored Maps URL only when it is HTTPS and actually on Google.
 *
 * `maps_url` is written by the Google Business Profile sync, but it is still
 * stored data rendered into an anchor. An unexpected `javascript:` or
 * third-party URL is dropped rather than rendered — the card then falls back
 * to the place id or the GBP dashboard.
 */
export function safeMapsUrl(raw: string | null | undefined): string | null {
  const href = safeHref(raw ?? "");
  if (!href) return null;

  try {
    const url = new URL(href);
    if (url.protocol !== "https:") return null;
    if (!isGoogleHost(url.hostname)) return null;

    // `goo.gl/maps/...` and `maps.app.goo.gl/...` are short links. For
    // google.com we only accept a Maps path, so a random Google search or
    // account URL can never masquerade as "verify on Maps".
    if (GOOGLE_HOSTS.has(url.hostname.toLowerCase())) return href;
    if (url.hostname.toLowerCase().startsWith("maps.google.")) return href;
    if (url.pathname.startsWith("/maps")) return href;
    return null;
  } catch {
    return null;
  }
}

/**
 * A Google Maps deep link for a Places API `place_id`.
 *
 * This is the documented `q=place_id:` form. The id is encoded because it is
 * provider data, not a URL fragment we control.
 */
export function mapsPlaceUrl(placeId: string | null | undefined): string | null {
  const id = (placeId ?? "").trim();
  if (!id || id.length > 512) return null;
  // Place ids are opaque but never contain whitespace or control characters.
  if (/[\s\u0000-\u001F\u007F]/.test(id)) return null;
  return `https://www.google.com/maps/place/?q=place_id:${encodeURIComponent(id)}`;
}

/**
 * Pick the most specific Maps link available for one listing.
 *
 * Prefer the stored Maps URL (it usually carries the business name and cid),
 * then the place id. `null` means "no listing-level link exists"; callers
 * should fall back to the GBP dashboard rather than search-by-name.
 */
export function listingMapsUrl(listing: {
  mapsUrl?: string | null;
  placeId?: string | null;
}): string | null {
  return safeMapsUrl(listing.mapsUrl) ?? mapsPlaceUrl(listing.placeId);
}
