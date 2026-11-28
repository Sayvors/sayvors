import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MetaAsset, MetaConnection } from "@/lib/api-meta";
import { I18nProvider } from "@/lib/i18n/I18nProvider";
import { queryKeys } from "@/lib/query-keys";
import MetaConnections from "./MetaConnections";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: null }),
}));

const phone: MetaAsset = {
  id: "phone-1",
  provider: "whatsapp",
  asset_type: "phone_number",
  external_asset_id: "15551234567",
  parent_asset_id: "waba-1",
  name: "Customer Care",
  username: null,
  phone: "+966 55 123 4567",
  active: true,
  status: "connected",
};

function connection(tokenHealth: MetaConnection["token_health"]): MetaConnection {
  return {
    id: "meta-1",
    provider: "whatsapp",
    connection_type: "embedded_signup",
    meta_business_id: "business-1",
    scopes: ["whatsapp_business_messaging"],
    status: "active",
    last_validated_at: "2026-11-28T08:00:00Z",
    last_successful_api_call_at: "2026-11-28T08:00:00Z",
    last_webhook_received_at: "2026-11-28T08:00:00Z",
    token_expires_at: "2027-02-26T08:00:00Z",
    token_last_rotated_at: "2026-10-30T08:00:00Z",
    token_health: tokenHealth,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function renderConnection(conn: MetaConnection) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(queryKeys.meta.connections(), { whatsapp: conn });
  client.setQueryData(queryKeys.meta.assets("all"), { whatsapp: [phone] });

  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <MetaConnections onNotice={vi.fn()} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("WhatsApp token health", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows automatic rotation for a healthy token without raw timestamps", () => {
    renderConnection(connection("healthy"));

    expect(screen.getByText("Token healthy · rotates automatically")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.queryByText("2027-02-26T08:00:00Z")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-10-30T08:00:00Z")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reconnect" })).not.toBeInTheDocument();
  });

  it("shows a pending state while the token rotates", () => {
    renderConnection(connection("rotating"));

    expect(screen.getByText("Token rotation pending")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reconnect" })).not.toBeInTheDocument();
  });

  it("requires reconnection instead of presenting the token as healthy", () => {
    renderConnection(connection("reauth_required"));

    expect(screen.getByText("Reconnect required")).toBeInTheDocument();
    expect(screen.getByText("Reconnect WhatsApp to restore access.")).toBeInTheDocument();
    expect(screen.queryByText("Connected")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconnect" })).toHaveAttribute(
      "href",
      "/dashboard/channels/whatsapp/connect",
    );
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  });

  it("renders the reconnect-required state and action in Arabic", () => {
    window.localStorage.setItem("sayvors.locale", "ar");
    renderConnection(connection("reauth_required"));

    expect(screen.getByText("يلزم إعادة الربط")).toBeInTheDocument();
    expect(screen.getByText("أعد ربط واتساب لاستعادة الوصول.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "إعادة الربط" })).toHaveAttribute(
      "href",
      "/dashboard/channels/whatsapp/connect",
    );
    expect(document.documentElement.dir).toBe("rtl");
  });
});
