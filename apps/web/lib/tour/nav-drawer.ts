/**
 * Lets the tour ask the dashboard nav to open.
 *
 * The tour's first step points at a sidebar item. On a phone the nav is an
 * off-screen drawer, so driver.js found the element in the DOM and spotlighted
 * nothing — the popover said "This is Connect" next to an empty screen.
 *
 * The tour provider and the sidebar are siblings under the dashboard layout, so
 * this goes through a window event rather than threading a ref or lifting
 * another provider through the tree. The events are namespaced and the payload
 * is empty on purpose: the only question being asked is "may I be seen?".
 */

const OPEN = "sayvors:nav-open";
const CLOSE = "sayvors:nav-close";

export function openNavDrawer(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(OPEN));
}

export function closeNavDrawer(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(CLOSE));
}

export const NAV_DRAWER_EVENTS = { OPEN, CLOSE } as const;

/**
 * Does this step point at something inside the dashboard nav?
 *
 * Anchors are declared as `[data-tour="nav-*"]`, so the key is the signal. A
 * step that targets page content must NOT trigger this: opening the nav over
 * the Reviews page would cover the thing being described.
 */
export function targetsNav(selector: string | null): boolean {
  return !!selector && selector.includes('"nav-');
}
