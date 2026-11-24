import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PlanGate from "./PlanGate";
import type { Entitlements, WebPlan } from "@/lib/api-billing";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api-billing", () => ({
  getEntitlements: vi.fn(),
  getPlans: vi.fn(),
}));

// Imported after the mock so these are the mocked functions.
import { getEntitlements, getPlans } from "@/lib/api-billing";

const mockEntitlements = vi.mocked(getEntitlements);
const mockPlans = vi.mocked(getPlans);

function entitlements(over: Partial<Entitlements> = {}): Entitlements {
  return {
    plan_slug: "free-trial",
    plan_name: "Free Trial",
    status: "active",
    max_channels: null,
    max_messages_per_month: null,
    messages_used_this_month: 0,
    messages_remaining: null,
    included_credit_cents: 0,
    features: { benchmarking: false },
    promo_active: false,
    granted_by: null,
    granted_until: null,
    ...over,
  };
}

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
    features: { benchmarking: true },
    sort_order: 2,
    ...over,
  };
}

function renderGate() {
  // A fresh client per test keeps query results from leaking between cases.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PlanGate surface="/dashboard/benchmark">
        <p>secret content</p>
      </PlanGate>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockPlans.mockResolvedValue([]);
});

describe("PlanGate", () => {
  it("renders the page when the plan includes the feature", async () => {
    mockEntitlements.mockResolvedValue(entitlements({ features: { benchmarking: true } }));

    renderGate();

    expect(await screen.findByText("secret content")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("never mounts the page while the plan is unknown", async () => {
    // A promise that never settles pins the pending state.
    mockEntitlements.mockReturnValue(new Promise<Entitlements>(() => {}));

    renderGate();

    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("names the cheapest plan that unlocks the page", async () => {
    mockEntitlements.mockResolvedValue(entitlements());
    mockPlans.mockResolvedValue([
      plan({ id: "growth", slug: "growth", name: "Growth", price_cents: 50_000, sort_order: 3 }),
      plan({ id: "pro", slug: "pro", name: "Pro", price_cents: 10_000, sort_order: 2 }),
      plan({ id: "starter", slug: "starter", name: "Starter", features: {}, sort_order: 1 }),
    ]);

    renderGate();

    const dialog = await screen.findByRole("dialog", { name: "Benchmarking is on Pro" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/Your Free Trial plan/)).toBeInTheDocument();
    // The gated page must not mount behind the overlay.
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });

  it("falls back to a generic title when no plan sells the feature", async () => {
    mockEntitlements.mockResolvedValue(entitlements());
    mockPlans.mockResolvedValue([plan({ features: {} })]);

    renderGate();

    expect(
      await screen.findByRole("dialog", { name: "Benchmarking needs a higher plan" }),
    ).toBeInTheDocument();
  });

  it("sends a declining tenant back to the dashboard", async () => {
    mockEntitlements.mockResolvedValue(entitlements());
    const user = userEvent.setup();

    renderGate();

    await user.click(await screen.findByRole("button", { name: "Not now" }));
    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("fails closed with a retry when entitlements cannot be read", async () => {
    mockEntitlements.mockRejectedValue(new Error("network down"));

    renderGate();

    expect(await screen.findByText("We couldn't check your plan.")).toBeInTheDocument();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
