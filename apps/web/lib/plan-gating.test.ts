import { describe, expect, it } from "vitest";
import {
  SURFACE_FEATURES,
  cheapestPlanFor,
  featureForPath,
  isPathLocked,
  planLabel,
  type PlanNames,
} from "./plan-gating";
import type { WebPlan } from "./api-billing";

function plan(over: Partial<WebPlan> = {}): WebPlan {
  return {
    id: "plan-1",
    slug: "pro",
    name: "Pro",
    description: null,
    price_cents: 10_000,
    included_credit_cents: 0,
    max_channels: null,
    max_messages_per_month: null,
    max_locations: null,
    max_team_members: null,
    max_regenerations_day: null,
    features: {},
    sort_order: 1,
    ...over,
  };
}

const NAMES: PlanNames = {
  trial: "Free Trial",
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  growth: "Growth",
  enterprise: "Enterprise",
};

describe("featureForPath", () => {
  it("maps a gated route to its catalog feature", () => {
    expect(featureForPath("/dashboard/benchmark")).toBe(SURFACE_FEATURES["/dashboard/benchmark"]);
    expect(featureForPath("/dashboard/verification")).toBe("verifications");
  });

  it("covers nested routes under a gated surface", () => {
    expect(featureForPath("/dashboard/databank/new")).toBe("databank");
  });

  it("matches whole segments only", () => {
    expect(featureForPath("/dashboard/leadership")).toBeNull();
    expect(featureForPath("/dashboard/leads-archive")).toBeNull();
  });

  it("ignores a trailing slash", () => {
    expect(featureForPath("/dashboard/leads/")).toBe("leads");
  });

  it("leaves free surfaces ungated", () => {
    expect(featureForPath("/dashboard/analytics")).toBeNull();
    expect(featureForPath("/dashboard")).toBeNull();
  });
});

describe("isPathLocked", () => {
  it("is false while entitlements are unknown", () => {
    expect(isPathLocked("/dashboard/benchmark", undefined)).toBe(false);
    expect(isPathLocked("/dashboard/benchmark", null)).toBe(false);
  });

  it("is true only when the feature is explicitly off", () => {
    expect(isPathLocked("/dashboard/benchmark", { benchmarking: true })).toBe(false);
    expect(isPathLocked("/dashboard/benchmark", { benchmarking: false })).toBe(true);
    // A plan that omits the key does not include the feature.
    expect(isPathLocked("/dashboard/benchmark", {})).toBe(true);
  });

  it("never locks a free surface", () => {
    expect(isPathLocked("/dashboard/analytics", {})).toBe(false);
  });
});

describe("cheapestPlanFor", () => {
  it("returns the lowest-priced plan that includes the feature", () => {
    const starter = plan({ slug: "starter", price_cents: 4_000, sort_order: 1 });
    const pro = plan({ slug: "pro", price_cents: 10_000, sort_order: 2, features: { benchmarking: true } });
    const growth = plan({ slug: "growth", price_cents: 50_000, sort_order: 3, features: { benchmarking: true } });
    expect(cheapestPlanFor([growth, pro, starter], "benchmarking")?.slug).toBe("pro");
  });

  it("breaks a price tie on catalog order", () => {
    const later = plan({ slug: "growth", sort_order: 3, features: { benchmarking: true } });
    const earlier = plan({ slug: "pro", sort_order: 2, features: { benchmarking: true } });
    expect(cheapestPlanFor([later, earlier], "benchmarking")?.slug).toBe("pro");
  });

  it("returns null when no plan sells the feature", () => {
    expect(cheapestPlanFor([plan({ features: {} })], "benchmarking")).toBeNull();
    expect(cheapestPlanFor([], "benchmarking")).toBeNull();
    expect(cheapestPlanFor(undefined, "benchmarking")).toBeNull();
  });
});

describe("planLabel", () => {
  it("maps seeded slugs to their translation key", () => {
    expect(planLabel("free-trial", NAMES)).toBe("Free Trial");
    expect(planLabel("growth", NAMES)).toBe("Growth");
  });

  it("falls back to the catalog name, then the slug", () => {
    expect(planLabel("legacy", NAMES, "Legacy Plan")).toBe("Legacy Plan");
    expect(planLabel("legacy", NAMES)).toBe("legacy");
    expect(planLabel(undefined, NAMES)).toBe("Free Trial");
  });
});
