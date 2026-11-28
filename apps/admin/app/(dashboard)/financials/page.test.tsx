import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchFinancials } from "@/lib/admin-api";
import { fetchAdminWhatsAppSpend } from "@/lib/whatsapp-spend";
import FinancialsPage from "./page";

vi.mock("@/lib/admin-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/admin-api")>()),
  fetchFinancials: vi.fn(),
  patchFinance: vi.fn(),
}));
vi.mock("@/lib/whatsapp-spend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/whatsapp-spend")>()),
  fetchAdminWhatsAppSpend: vi.fn(),
}));

const mockFinancials = vi.mocked(fetchFinancials);
const mockSpend = vi.mocked(fetchAdminWhatsAppSpend);

describe("FinancialsPage WhatsApp spend", () => {
  beforeEach(() => {
    mockFinancials.mockReset();
    mockSpend.mockReset();
    mockFinancials.mockResolvedValue({
      month: "2026-11",
      items: [],
      total: 0,
      totals: {
        expected_revenue_cents: 0,
        collected_cents: 0,
        infra_cost_micro: 0,
        margin_micro: 0,
        unpaid_count: 0,
      },
    });
    mockSpend.mockResolvedValue({ days: 30, items: [], total: 0, totals: [] });
  });

  afterEach(cleanup);

  it("mounts the WhatsApp spend panel alongside monthly financials", async () => {
    render(<FinancialsPage />);

    expect(await screen.findByRole("region", { name: "WhatsApp spend" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Financials" })).toBeInTheDocument();
    expect(mockSpend).toHaveBeenCalledWith(30);
  });
});
