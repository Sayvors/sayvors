export const CONNECT_IMPORT_STORAGE_KEY = "sayvors.connectImportSession";
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
