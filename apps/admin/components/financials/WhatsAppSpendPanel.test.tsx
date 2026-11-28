import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAdminWhatsAppSpend,
  type WhatsAppSpendResponse,
  type WhatsAppSpendRow,
} from "@/lib/whatsapp-spend";
import WhatsAppSpendPanel from "./WhatsAppSpendPanel";

vi.mock("@/lib/whatsapp-spend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/whatsapp-spend")>()),
  fetchAdminWhatsAppSpend: vi.fn(),
}));

const mockFetch = vi.mocked(fetchAdminWhatsAppSpend);

function row(overrides: Partial<WhatsAppSpendRow> = {}): WhatsAppSpendRow {
  return {
    tenant_id: "tenant-1",
    tenant_name: "Acme",
    tenant_email: "owner@example.com",
    waba_id: "waba-1",
    waba_name: "Acme WhatsApp",
    funding_mode: "shared_credit_line",
    volume: 50,
    approximate_cost: 5,
    currency: "USD",
    cost_availability: "available",
    last_meta_sync_at: "2026-11-28T09:00:00Z",
    sync_status: "synced",
    ...overrides,
  };
}

function response(overrides: Partial<WhatsAppSpendResponse> = {}): WhatsAppSpendResponse {
  return {
    days: 30,
    total: 3,
    totals: [],
    items: [
      row({ funding_mode: "direct_client", volume: 100, approximate_cost: 10, last_meta_sync_at: "2026-11-28T08:00:00Z" }),
      row(),
      row({
        tenant_id: "tenant-2",
        tenant_name: "Beta",
        waba_id: "waba-3",
        waba_name: "Beta WhatsApp",
        volume: 20,
        approximate_cost: null,
        currency: "USD",
        cost_availability: "unavailable",
        last_meta_sync_at: null,
        sync_status: "pending",
      }),
    ],
    ...overrides,
  };
}

describe("WhatsAppSpendPanel", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue(response());
  });

  afterEach(cleanup);

  it("separates client-direct and Sayvors-payable spend and excludes direct spend from margin", async () => {
    render(<WhatsAppSpendPanel />);

    expect(await screen.findByRole("region", { name: "WhatsApp spend" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Delivered volume" })).getByText("170")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Client-direct Meta spend" })).getByText("$10.00")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Sayvors-payable Meta spend" })).getByText("$5.00")).toBeInTheDocument();
    expect(screen.getByText("Client-direct Meta spend is excluded from Sayvors platform cost and margin.")).toBeInTheDocument();
  });

  it("shows tenant/WABA rows with volume, funding, availability, native cost, and last sync", async () => {
    render(<WhatsAppSpendPanel />);

    const table = await screen.findByRole("table", { name: "WhatsApp spend by tenant and WABA" });
    const beta = within(table).getByRole("row", { name: /Beta/ });
    expect(beta).toHaveTextContent("Beta WhatsApp");
    expect(beta).toHaveTextContent("20");
    expect(beta).toHaveTextContent("Sayvors-payable");
    expect(beta).toHaveTextContent("Unavailable");
    expect(beta).toHaveTextContent("Cost unavailable from Meta");
    expect(beta).toHaveTextContent("Syncing…");
    const acmeRows = within(table).getAllByRole("row", { name: /Acme/ });
    expect(acmeRows).toHaveLength(2);
    expect(acmeRows.some((item) => item.textContent?.includes("Client-direct"))).toBe(true);
    expect(within(acmeRows[0]).getByText("$10.00")).toBeInTheDocument();
  });

  it("keeps the previous sync time visible on a row while Meta is syncing again", async () => {
    mockFetch.mockResolvedValue(response({
      items: [row({ last_meta_sync_at: "2026-11-27T08:00:00Z", sync_status: "syncing" })],
      totals: [],
      total: 1,
    }));
    render(<WhatsAppSpendPanel />);

    const table = await screen.findByRole("table", { name: "WhatsApp spend by tenant and WABA" });
    const item = within(table).getByRole("row", { name: /Acme/ });
    expect(item).toHaveTextContent("Syncing…");
    expect(within(item).getByText(/Nov 27, 2026/)).toBeInTheDocument();
  });

  it("keeps delivered volume visible and marks partial Meta cost without estimating it", async () => {
    render(<WhatsAppSpendPanel />);

    expect(await screen.findByText("Some Meta costs are unavailable. Delivered volume remains visible; missing costs are not estimated.")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Delivered volume" })).getByText("170")).toBeInTheDocument();
    expect(screen.getByText("Approximate Meta amount in native currency; not a final invoice.")).toBeInTheDocument();
  });

  it("announces the initial loading state", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<WhatsAppSpendPanel />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading WhatsApp spend…");
    expect(screen.getByRole("region", { name: "WhatsApp spend" })).toHaveAttribute("aria-busy", "true");
  });

  it("exposes a retry for recoverable errors", async () => {
    mockFetch.mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    render(<WhatsAppSpendPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load WhatsApp spend.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("table", { name: "WhatsApp spend by tenant and WABA" })).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("shows an explicit empty state", async () => {
    mockFetch.mockResolvedValue(response({ items: [], totals: [], total: 0 }));
    render(<WhatsAppSpendPanel />);

    expect(await screen.findByText("No WhatsApp spend rows for this period.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("reloads when the spend period changes", async () => {
    const user = userEvent.setup();
    render(<WhatsAppSpendPanel />);
    await screen.findByRole("table", { name: "WhatsApp spend by tenant and WABA" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Spend period" }), "90");

    expect(await screen.findByRole("table", { name: "WhatsApp spend by tenant and WABA" })).toBeInTheDocument();
    expect(mockFetch).toHaveBeenLastCalledWith(90);
  });

  it("renders Arabic copy with RTL semantics", async () => {
    const user = userEvent.setup();
    render(<WhatsAppSpendPanel />);
    await screen.findByRole("region", { name: "WhatsApp spend" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "ar");

    const panel = screen.getByRole("region", { name: "إنفاق واتساب" });
    expect(panel).toHaveAttribute("dir", "rtl");
    expect(panel).toHaveAttribute("lang", "ar");
    expect(within(panel).getAllByText("الحجم المُسلَّم")).toHaveLength(2);
    expect(within(panel).getByText("التكلفة غير متاحة من Meta")).toBeInTheDocument();
  });
});
