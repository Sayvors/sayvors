export const CONNECT_IMPORT_STORAGE_KEY = "sayvors.connectImportSession";
export const CONNECT_IMPORT_DISMISSED_KEY = "sayvors.connectImportDismissed";
export const CONNECT_IMPORT_EVENT = "sayvors:connect-import";

export function setActiveConnectImport(sessionId: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CONNECT_IMPORT_STORAGE_KEY, sessionId);
  window.dispatchEvent(
    new CustomEvent(CONNECT_IMPORT_EVENT, { detail: { sessionId } }),
  );
}

export function clearActiveConnectImport() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(CONNECT_IMPORT_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent(CONNECT_IMPORT_EVENT, { detail: { sessionId: null } }));
}

/** Sessions the merchant explicitly closed. The auto-open poll must never
 *  resurrect them — keyed by session id, so a later import still opens. */
export function dismissConnectImport(sessionId: string) {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(CONNECT_IMPORT_DISMISSED_KEY);
    const ids: string[] = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(ids) || ids.includes(sessionId)) return;
    window.localStorage.setItem(
      CONNECT_IMPORT_DISMISSED_KEY,
      JSON.stringify([...ids, sessionId]),
    );
  } catch {
    /* private mode — dismissal just won't persist */
  }
}

export function isConnectImportDismissed(sessionId: string | null): boolean {
  if (typeof window === "undefined" || !sessionId) return false;
  try {
    const raw = window.localStorage.getItem(CONNECT_IMPORT_DISMISSED_KEY);
    const ids: string[] = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) && ids.includes(sessionId);
  } catch {
    return false;
  }
}
