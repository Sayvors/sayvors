/** Guided tour script — one step per anchor, possibly across pages. */

export interface TourStep {
  /** Page the anchor lives on. */
  route: string;
  /** `[data-tour=…]` selector; null renders a centered popover. */
  selector: string | null;
  title: string;
  body: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    route: "/dashboard",
    selector: '[data-tour="nav-connect"]',
    title: "Connect — link your business",
    body: "This is Connect, where Sayvors links to your Google Business Profile. Everything starts here.",
  },
  {
    route: "/dashboard/channels",
    selector: '[data-tour="connect-location"]',
    title: "Connect your Google location",
    body: "Connect your listing here — it links your Google Business Profile so Sayvors can read and reply to your reviews.",
  },
  {
    route: "/dashboard/channels",
    selector: '[data-tour="sync-now"]',
    title: "Sync with Google",
    body: "Sync now pulls your latest reviews and business info straight from Google. Sync runs automatically, but you can do it any time.",
  },
  {
    route: "/dashboard/locations",
    selector: '[data-tour="add-location"]',
    title: "Locations — your business hub",
    body: "Once connected, everything about your business lives here: profile, hours, services, phone, website. Switch locations and edit anything.",
  },
  {
    route: "/dashboard/reviews",
    selector: '[data-tour="reviews-header"]',
    title: "Reviews — read & respond",
    body: "Every review lands here. AI drafts replies for you — read, edit, run the engine again, or approve and publish to Google.",
  },
  {
    route: "/dashboard",
    selector: '[data-tour="attention"]',
    title: "Needs attention",
    body: "The dashboard pins exactly what needs you: replies waiting for approval and anything that failed. When this says All clear, you're done.",
  },
];
