import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api-rag";
import { fetchWhatsAppUsage } from "./api-whatsapp-usage";

vi.mock("./api-rag", () => ({ apiFetch: vi.fn() }));

const mockFetch = vi.mocked(apiFetch);

describe("fetchWhatsAppUsage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("requests the selected period from the tenant billing endpoint", async () => {
    const response = {
      used: 120,
      limit: 1000,
      remaining: 880,
      approximate_cost: null,
      currency: null,
      cost_availability: "unavailable",
      funding_mode: "shared_credit_line",
      last_meta_sync_at: null,
      sync_status: "pending",
      totals: [],
      breakdowns: { by_waba: [], by_phone: [], by_category: [] },
    };
    mockFetch.mockResolvedValue(response);

    await expect(fetchWhatsAppUsage(90)).resolves.toBe(response);
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/billing/whatsapp-usage?days=90");
  });

  it("defaults to the 30-day Meta spend window", async () => {
    mockFetch.mockResolvedValue({});

    await fetchWhatsAppUsage();

    expect(mockFetch).toHaveBeenCalledWith("/api/v1/billing/whatsapp-usage?days=30");
  });
});
