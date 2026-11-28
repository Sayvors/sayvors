import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetch } from "./admin-api";
import {
  fetchAdminWhatsAppSpend,
  summarizeWhatsAppSpend,
  type WhatsAppSpendResponse,
  type WhatsAppSpendRow,
} from "./whatsapp-spend";

vi.mock("./admin-api", () => ({ adminFetch: vi.fn() }));

const mockFetch = vi.mocked(adminFetch);

function row(overrides: Partial<WhatsAppSpendRow> = {}): WhatsAppSpendRow {
  return {
    tenant_id: "tenant-1",
    tenant_name: "Acme",
    tenant_email: "owner@example.com",
    waba_id: "waba-1",
    waba_name: "Acme WhatsApp",
    funding_mode: "shared_credit_line",
    volume: 10,
    approximate_cost: 1.25,
    currency: "USD",
    cost_availability: "available",
    last_meta_sync_at: "2026-11-28T08:00:00Z",
    sync_status: "synced",
    ...overrides,
  };
}

function response(overrides: Partial<WhatsAppSpendResponse> = {}): WhatsAppSpendResponse {
  return { days: 30, items: [], total: 0, totals: [], ...overrides };
}

describe("fetchAdminWhatsAppSpend", () => {
  beforeEach(() => mockFetch.mockReset());

  it("requests the selected period from the admin spend endpoint", async () => {
    const data = response();
    mockFetch.mockResolvedValue(data);

    await expect(fetchAdminWhatsAppSpend(365)).resolves.toBe(data);
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/admin/whatsapp-spend?days=365");
  });

  it("defaults to 30 days", async () => {
    mockFetch.mockResolvedValue(response());

    await fetchAdminWhatsAppSpend();

    expect(mockFetch).toHaveBeenCalledWith("/api/v1/admin/whatsapp-spend?days=30");
  });
});

describe("summarizeWhatsAppSpend", () => {
  it("separates direct-client spend from Sayvors-payable spend by native currency", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [
        row({ funding_mode: "direct_client", volume: 100, approximate_cost: 10 }),
        row({ funding_mode: "shared_credit_line", volume: 50, approximate_cost: 5 }),
        row({ funding_mode: "platform_liable", volume: 25, approximate_cost: 3, currency: "SAR" }),
        row({ volume: 20, approximate_cost: null, currency: "USD", cost_availability: "unavailable" }),
      ],
    }));

    expect(summary.deliveredVolume).toBe(195);
    expect(summary.directClientByCurrency).toEqual([
      { currency: "USD", approximateCost: 10, volume: 100 },
    ]);
    expect(summary.sayvorsPayableByCurrency).toEqual([
      { currency: "SAR", approximateCost: 3, volume: 25 },
      { currency: "USD", approximateCost: 5, volume: 50 },
    ]);
    expect(summary.unavailableCostVolume).toBe(20);
    expect(summary.directClientUnavailableCostVolume).toBe(0);
    expect(summary.sayvorsPayableUnavailableCostVolume).toBe(20);
    expect(summary.partial).toBe(true);
    expect(summary.lastSyncAt).toBe("2026-11-28T08:00:00Z");
  });

  it("uses backend totals instead of double-counting the displayed rows", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [row({ volume: 10, approximate_cost: 1 })],
      totals: [row({ volume: 100, approximate_cost: 10 })],
    }));

    expect(summary.deliveredVolume).toBe(100);
    expect(summary.sayvorsPayableByCurrency).toEqual([
      { currency: "USD", approximateCost: 10, volume: 100 },
    ]);
  });

  it("treats a reported zero cost as available rather than unavailable", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [row({ approximate_cost: 0 })],
    }));

    expect(summary.sayvorsPayableByCurrency).toEqual([
      { currency: "USD", approximateCost: 0, volume: 10 },
    ]);
    expect(summary.unavailableCostVolume).toBe(0);
    expect(summary.directClientUnavailableCostVolume).toBe(0);
    expect(summary.sayvorsPayableUnavailableCostVolume).toBe(0);
    expect(summary.partial).toBe(false);
  });

  it("excludes costs Meta marks unavailable even if an amount is present", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [row({ approximate_cost: 9, cost_availability: "unavailable" })],
    }));

    expect(summary.sayvorsPayableByCurrency).toEqual([]);
    expect(summary.sayvorsPayableUnavailableCostVolume).toBe(10);
  });

  it("does not invent a currency conversion or a latest sync time", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [
        row({ approximate_cost: 7, currency: null, last_meta_sync_at: null }),
        row({ approximate_cost: null, currency: null, cost_availability: "unavailable", last_meta_sync_at: "invalid" }),
      ],
    }));

    expect(summary.directClientByCurrency).toEqual([]);
    expect(summary.sayvorsPayableByCurrency).toEqual([]);
    expect(summary.unavailableCostVolume).toBe(20);
    expect(summary.directClientUnavailableCostVolume).toBe(0);
    expect(summary.sayvorsPayableUnavailableCostVolume).toBe(20);
    expect(summary.lastSyncAt).toBeNull();
  });

  it("attributes unavailable cost volume to the correct funding mode", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [
        row({ funding_mode: "direct_client", volume: 40, approximate_cost: null, currency: "USD", cost_availability: "unavailable" }),
        row({ funding_mode: "platform_liable", volume: 5, approximate_cost: null, currency: "USD", cost_availability: "unavailable" }),
      ],
    }));

    expect(summary.directClientUnavailableCostVolume).toBe(40);
    expect(summary.sayvorsPayableUnavailableCostVolume).toBe(5);
  });

  it("keeps the newest valid sync timestamp across funding modes", () => {
    const summary = summarizeWhatsAppSpend(response({
      items: [
        row({ funding_mode: "direct_client", last_meta_sync_at: "2026-11-27T08:00:00Z" }),
        row({ funding_mode: "platform_liable", last_meta_sync_at: "2026-11-28T09:00:00Z" }),
      ],
    }));

    expect(summary.lastSyncAt).toBe("2026-11-28T09:00:00Z");
  });
});
