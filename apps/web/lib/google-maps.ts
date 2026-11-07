/**
 * One Google Maps JS loader for the whole app.
 *
 * The script can only be inserted once; a second insertion either fetches it
 * twice or hangs waiting for a load event that already fired. Keep the
 * promise here so every map surface (locations overview, address pin) shares
 * the same load.
 */
const SCRIPT_ID = "sayvors-google-maps";

let scriptPromise: Promise<void> | null = null;

export function loadGoogleMaps(apiKey: string): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Google Maps needs a browser."));
  }
  const w = window as unknown as { google?: { maps?: unknown } };
  if (w.google?.maps) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      if (w.google?.maps) {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Maps script failed")), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.async = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&v=weekly&libraries=marker,geometry`;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error("Maps script failed"));
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}
