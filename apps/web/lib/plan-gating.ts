import type { WebPlan } from "./api-billing";
import type { Dict } from "./i18n/en";

/* ── Which surfaces a plan actually sells ───────────────────────────────
 *
 * The sidebar crowns a route and the route's PlanGate blocks it — both read
 * this one map, so the badge can never promise a lock the page does not
 * enforce (or the reverse).
 *
 * Only list a route when its feature is genuinely sold as part of a plan.
 * A crown on a page that works without the feature teaches users to ignore
 * crowns. Routes absent here are never gated.
 *
 * Keys are full route prefixes. Values must exist in
 * services/api/app/modules/billing/features.py FEATURE_CATALOG.
 */
export const SURFACE_FEATURES = {
  "/dashboard/benchmark": "benchmarking",
  "/dashboard/databank": "databank",
  "/dashboard/verification": "verifications",
  "/dashboard/growth": "growth",
  "/dashboard/leads": "leads",
} as const;

export type GatedSurface = keyof typeof SURFACE_FEATURES;

export type PlanNames = Dict["dashboard"]["plans"]["planNames"];
export type PlanNameKey = keyof PlanNames;

/* Seeded plan slugs are not translation keys ("free-trial" is the trial), so
 * the catalog slug has to be mapped before it can be shown to a tenant. */
const PLAN_SLUG_KEYS: Record<string, PlanNameKey> = {
  "free-trial": "trial",
  free: "free",
  starter: "starter",
  pro: "pro",
  growth: "growth",
  enterprise: "enterprise",
};

function normalizePath(pathname: string): string {
  // A trailing slash must not turn "/dashboard/leads/" into an ungated route.
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

/** The plan feature that unlocks `pathname`, or null when the route is free.
 *
 *  Longest prefix wins, so a future nested route can be gated separately from
 *  its parent. Matches whole segments only: "/dashboard/leads-archive" is not
 *  covered by "/dashboard/leads".
 */
export function featureForPath(pathname: string): string | null {
  const path = normalizePath(pathname);
  let match: { route: string; feature: string } | null = null;
  for (const [route, feature] of Object.entries(SURFACE_FEATURES)) {
    if (path !== route && !path.startsWith(`${route}/`)) continue;
    if (!match || route.length > match.route.length) match = { route, feature };
  }
  return match?.feature ?? null;
}

/** Whether the plan blocks `pathname`.
 *
 *  Unknown entitlements return false: while the catalog is in flight the UI
 *  must not flash a paywall at a paying tenant. The API is the enforcement
 *  point, so failing open here cannot grant access.
 */
export function isPathLocked(
  pathname: string,
  features: Record<string, boolean> | null | undefined,
): boolean {
  const feature = featureForPath(pathname);
  if (!feature || !features) return false;
  return features[feature] !== true;
}

/** Cheapest plan that includes `feature`, or null when none does.
 *
 *  "Cheapest" is the only honest upsell: the tenant should be pointed at the
 *  plan that actually unlocks the page, not the top of the price list. Ties
 *  break on catalog order so the answer is deterministic.
 */
export function cheapestPlanFor(
  plans: readonly WebPlan[] | null | undefined,
  feature: string,
): WebPlan | null {
  if (!plans?.length) return null;
  const eligible = plans.filter((plan) => plan.features?.[feature] === true);
  if (eligible.length === 0) return null;
  return [...eligible].sort(
    (a, b) => a.price_cents - b.price_cents || a.sort_order - b.sort_order,
  )[0];
}

/** Localized plan name for a slug, falling back to the catalog name. */
export function planLabel(
  slug: string | null | undefined,
  names: PlanNames,
  fallback = "",
): string {
  const key = slug ? PLAN_SLUG_KEYS[slug] : undefined;
  return (key ? names[key] : "") || fallback || slug || names.trial;
}
