import { API_BASE } from "@/lib/api-base";

/**
 * Resolve a stored media URL for the browser.
 *
 * Uploaded avatars/covers are served by the API at `/media-files/...`. The
 * database stores the URL generated at upload time, which can carry an origin
 * the browser cannot use:
 *
 * - an internal container host (`http://api:8000`),
 * - a localhost URL from a tunnel, seen by a remote browser,
 * - `http://` on an `https` page (mixed content, blocked before any request).
 *
 * Provider CDN URLs, data: URLs and blob: previews are left alone. An
 * already-public absolute URL is also left alone: it may be the API's real
 * origin, and rewriting it would only break local development where the API
 * is on a different port but still reachable.
 */
export function resolveMediaUrl(
  url: string | null | undefined,
): string | null {
  if (!url) return null;
  if (
    url.startsWith("data:") ||
    url.startsWith("blob:") ||
    !url.includes("/media-files/")
  ) {
    return url;
  }
  if (typeof window === "undefined") return url;

  let parsed: URL;
  try {
    parsed = new URL(url, window.location.origin);
  } catch {
    return url;
  }

  const pageHost = window.location.hostname;
  const pageIsLocal =
    pageHost === "localhost" || pageHost === "127.0.0.1" || pageHost === "[::1]";
  const urlIsLocal =
    parsed.hostname === "localhost" ||
    parsed.hostname === "127.0.0.1" ||
    parsed.hostname === "[::1]";
  // A single-label host is a Docker service name ("api", "web"), never a
  // public origin.
  const internalHost = !parsed.hostname.includes(".") && !urlIsLocal;
  const mixedContent =
    parsed.protocol === "http:" && window.location.protocol === "https:";
  const localUrlOnRemotePage = urlIsLocal && !pageIsLocal;

  if (!internalHost && !mixedContent && !localUrlOnRemotePage) {
    return url;
  }

  const base = API_BASE.replace(/\/$/, "");
  return `${base}${parsed.pathname}${parsed.search}${parsed.hash}`;
}
