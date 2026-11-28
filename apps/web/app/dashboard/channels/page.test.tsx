import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api-rag";
import { I18nProvider } from "@/lib/i18n/I18nProvider";
import ChannelsPage from "./page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("@/lib/api-rag", () => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/mutation-hooks", () => ({
  useUpdateChannelConfig: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock("@/components/channels/MetaConnections", () => ({ default: () => null }));

const mockFetch = vi.mocked(apiFetch);

describe("ChannelsPage WhatsApp usage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockFetch.mockReset();
    mockFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/billing/whatsapp-usage")) {
        return {
          used: 10,
          limit: 100,
          remaining: 90,
          approximate_cost: null,
          currency: null,
          cost_availability: "unavailable",
          funding_mode: "shared_credit_line",
          last_meta_sync_at: null,
          sync_status: "pending",
          totals: [],
          breakdowns: { by_waba: [], by_phone: [], by_category: [] },
        };
      }
      return { channels: [] };
    });
  });

  afterEach(cleanup);

  it("mounts the WhatsApp usage and spend card on the Channels page", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider>
          <ChannelsPage />
        </I18nProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("region", { name: "WhatsApp usage & spend" })).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/billing/whatsapp-usage?days=30");
  });
});
