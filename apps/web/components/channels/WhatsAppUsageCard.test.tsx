import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n/I18nProvider";
import {
  fetchWhatsAppUsage,
  type WhatsAppUsageResponse,
} from "@/lib/api-whatsapp-usage";
import WhatsAppUsageCard from "./WhatsAppUsageCard";

vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("@/lib/api-whatsapp-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-whatsapp-usage")>()),
  fetchWhatsAppUsage: vi.fn(),
}));

const mockFetch = vi.mocked(fetchWhatsAppUsage);

function usage(overrides: Partial<WhatsAppUsageResponse> = {}): WhatsAppUsageResponse {
  return {
    used: 750,
    limit: 1000,
    remaining: 250,
    approximate_cost: null,
    currency: null,
    cost_availability: "unavailable",
    funding_mode: "shared_credit_line",
    last_meta_sync_at: null,
    sync_status: "pending",
    totals: [],
    breakdowns: { by_waba: [], by_phone: [], by_category: [] },
    ...overrides,
  };
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <WhatsAppUsageCard />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("WhatsAppUsageCard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockFetch.mockReset();
    mockFetch.mockResolvedValue(usage());
  });

  afterEach(cleanup);

  it("shows the real-time local quota count, limit, remaining, and attempts policy", async () => {
    renderCard();

    await screen.findByText("750");
    const card = screen.getByRole("region", { name: "WhatsApp usage & spend" });
    expect(card).toHaveTextContent("750");
    expect(card).toHaveTextContent("1,000");
    expect(card).toHaveTextContent("250");
    expect(card).toHaveTextContent("Local quota usage");
    expect(card).toHaveTextContent(
      "Counts send attempts that may have reached Meta, including failed or ambiguous attempts.",
    );
    expect(screen.getByRole("progressbar", { name: "WhatsApp quota used" })).toHaveAttribute(
      "value",
      "750",
    );
  });

  it("shows a pending Meta sync without inventing a last-sync time", async () => {
    renderCard();

    expect(await screen.findByText("Syncing from Meta…")).toBeInTheDocument();
    expect(screen.queryByText(/Last Meta sync/)).not.toBeInTheDocument();
  });

  it("keeps the previous successful sync visible while Meta is syncing again", async () => {
    mockFetch.mockResolvedValue(usage({ last_meta_sync_at: "2026-11-27T08:00:00Z" }));
    renderCard();

    expect(await screen.findByText("Syncing from Meta…")).toBeInTheDocument();
    expect(screen.getByText("Last Meta sync")).toBeInTheDocument();
    expect(screen.getByText(/Nov 27, 2026/)).toBeInTheDocument();
  });

  it("states explicitly when Meta cost is unavailable", async () => {
    renderCard();

    expect(await screen.findByText("Cost unavailable from Meta")).toBeInTheDocument();
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });

  it("labels an available direct-client cost as approximate and Meta-billed", async () => {
    mockFetch.mockResolvedValue(usage({
      approximate_cost: 12.34,
      currency: "USD",
      cost_availability: "available",
      funding_mode: "direct_client",
      sync_status: "synced",
      last_meta_sync_at: "2026-11-28T08:00:00Z",
    }));
    renderCard();

    expect(await screen.findByText("$12.34")).toBeInTheDocument();
    expect(screen.getByText("Approximate Meta spend")).toBeInTheDocument();
    expect(screen.getByText("Billed to your Meta account")).toBeInTheDocument();
    expect(screen.getByText(/Last Meta sync/)).toBeInTheDocument();
  });

  it("fails closed when Meta marks a cost unavailable or omits its native currency", async () => {
    mockFetch.mockResolvedValue(usage({
      totals: [
        {
          funding_mode: "shared_credit_line",
          volume: 10,
          approximate_cost: 7,
          currency: null,
          cost_availability: "available",
          last_meta_sync_at: null,
        },
        {
          funding_mode: "shared_credit_line",
          volume: 10,
          approximate_cost: 9,
          currency: "USD",
          cost_availability: "unavailable",
          last_meta_sync_at: null,
        },
      ],
    }));
    renderCard();

    expect(await screen.findAllByText("Cost unavailable from Meta")).toHaveLength(2);
    expect(screen.queryByText("$9.00")).not.toBeInTheDocument();
    expect(screen.queryByText("7")).not.toBeInTheDocument();
  });

  it("keeps local quota visible when only some Meta costs are unavailable", async () => {
    mockFetch.mockResolvedValue(usage({
      approximate_cost: 5,
      currency: "USD",
      cost_availability: "partial",
      totals: [{
        funding_mode: "shared_credit_line",
        volume: 20,
        approximate_cost: 5,
        currency: "USD",
        cost_availability: "partial",
        last_meta_sync_at: "2026-11-28T08:00:00Z",
      }],
    }));
    renderCard();

    expect(await screen.findByText("$5.00")).toBeInTheDocument();
    expect(screen.getByText("Some Meta costs are unavailable; local quota is unaffected.")).toBeInTheDocument();
    expect(screen.getByText("750")).toBeInTheDocument();
  });

  it("explains an empty period instead of showing a blank card", async () => {
    mockFetch.mockResolvedValue(usage({ used: 0, remaining: 1000 }));
    renderCard();

    expect(await screen.findByText("No WhatsApp usage in this period.")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("offers retry after a recoverable load error", async () => {
    mockFetch.mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    renderCard();

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load WhatsApp usage.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Cost unavailable from Meta")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("announces the initial loading state", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    renderCard();

    expect(screen.getByRole("status")).toHaveTextContent("Loading WhatsApp usage…");
    expect(screen.getByRole("region", { name: "WhatsApp usage & spend" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("reloads the selected 90-day period", async () => {
    const user = userEvent.setup();
    renderCard();
    await screen.findByText("Live local count");

    await user.selectOptions(screen.getByRole("combobox", { name: "Meta spend period" }), "90");

    expect(await screen.findByText("Syncing from Meta…")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenLastCalledWith(90);
  });

  it("renders WABA, phone, and category attribution without inventing unavailable costs", async () => {
    mockFetch.mockResolvedValue(usage({
      breakdowns: {
        by_waba: [{
          waba_id: "waba-1",
          waba_name: "Acme WABA",
          funding_mode: "shared_credit_line",
          volume: 12,
          approximate_cost: null,
          currency: null,
          cost_availability: "unavailable",
          last_meta_sync_at: null,
        }],
        by_phone: [{
          phone: "+966 55 123 4567",
          funding_mode: "shared_credit_line",
          volume: 12,
          approximate_cost: 2.5,
          currency: "USD",
          cost_availability: "available",
          last_meta_sync_at: null,
        }],
        by_category: [{
          category: "MARKETING",
          funding_mode: "shared_credit_line",
          volume: 12,
          approximate_cost: 2.5,
          currency: "USD",
          cost_availability: "available",
          last_meta_sync_at: null,
        }],
      },
    }));
    const user = userEvent.setup();
    renderCard();
    await screen.findByText("750");

    await user.click(screen.getByText("View WABA, phone & category breakdown"));

    expect(screen.getByText("Acme WABA")).toBeInTheDocument();
    expect(screen.getByText("+966 55 123 4567")).toBeInTheDocument();
    expect(screen.getByText("MARKETING")).toBeInTheDocument();
    expect(screen.getAllByText("Cost unavailable from Meta").length).toBeGreaterThan(0);
  });

  it("renders an unlimited plan without a misleading progress maximum", async () => {
    mockFetch.mockResolvedValue(usage({ limit: null, remaining: null }));
    renderCard();

    expect(await screen.findAllByText("Unlimited")).toHaveLength(2);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("renders Arabic copy and RTL semantics", async () => {
    window.localStorage.setItem("sayvors.locale", "ar");
    renderCard();

    expect(await screen.findByText("المستخدم محلياً")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "استخدام واتساب والإنفاق" })).toBeInTheDocument();
    expect(screen.getByText("المتبقي")).toBeInTheDocument();
    expect(screen.getByText("التكلفة غير متاحة من Meta")).toBeInTheDocument();
    expect(document.documentElement.dir).toBe("rtl");
  });
});
