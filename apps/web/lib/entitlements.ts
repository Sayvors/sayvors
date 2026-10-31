"use client";

/* Global entitlement-denial bus.
 *
 * apiFetch dispatches here whenever the API answers 403/429 with the
 * X-Entitlement-Denied header (see billing/entitlements.py). The UpgradePrompt
 * modal subscribes and shows the "this is premium" dialog. An event bus —
 * rather than a thrown typed error — means the prompt fires even when the
 * caller catches and toasts the failure, which every existing call site does.
 */

export interface EntitlementDeniedDetail {
  /** Feature key ("leads", "voice", …) or "quota" for usage caps. */
  feature: string | null;
  /** Human-readable server message, shown in the modal. */
  message: string;
}

const EVENT_NAME = "sayvors:entitlement-denied";

/** Must match billing/entitlements.py ENTITLEMENT_DENIED_HEADER. */
export const ENTITLEMENT_DENIED_HEADER = "X-Entitlement-Denied";

export function notifyEntitlementDenied(detail: EntitlementDeniedDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<EntitlementDeniedDetail>(EVENT_NAME, { detail }));
}

export function subscribeEntitlementDenied(
  handler: (detail: EntitlementDeniedDetail) => void,
): () => void {
  const listener = (e: Event) => {
    handler((e as CustomEvent<EntitlementDeniedDetail>).detail);
  };
  window.addEventListener(EVENT_NAME, listener);
  return () => window.removeEventListener(EVENT_NAME, listener);
}
