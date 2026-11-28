import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const billing = vi.hoisted(() => ({
  getBudget: vi.fn(),
  getEntitlements: vi.fn(),
  getPlans: vi.fn(),
}));
let mobile = true;

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard/ai-visibility" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: ComponentProps<"a">) => <a href={href} {...props}>{children}</a>,
}));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("@tanstack/react-query", () => ({ useQuery: vi.fn(() => ({ data: undefined })) }));
vi.mock("@/lib/api-billing", () => billing);
vi.mock("@/lib/api-rag", () => ({
  apiFetch: vi.fn().mockResolvedValue({ channels: [], connections: [] }),
}));
vi.mock("@/lib/i18n/I18nProvider", async () => {
  const en = await vi.importActual<typeof import("@/lib/i18n/en")>("@/lib/i18n/en");
  return { useI18n: () => ({ locale: "en", dir: "ltr", t: en.default }) };
});

import Sidebar from "./Sidebar";

beforeEach(() => {
  vi.clearAllMocks();
  mobile = true;
  billing.getBudget.mockResolvedValue({
    plan: "pro",
    balance_cents: 500,
    balance_dollars: 5,
    currency: "USD",
  });
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches: mobile,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});

describe("Sidebar mobile drawer", () => {
  it("makes the closed mobile drawer inert so its links leave keyboard order", async () => {
    render(<Sidebar />);
    const sidebar = document.getElementById("dashboard-sidebar")!;

    await waitFor(() => expect(sidebar).toHaveAttribute("aria-hidden", "true"));
    expect(sidebar).toHaveAttribute("inert");
  });

  it("removes inert and aria-hidden when the mobile drawer opens", async () => {
    render(<Sidebar />);
    const sidebar = document.getElementById("dashboard-sidebar")!;
    await waitFor(() => expect(sidebar).toHaveAttribute("inert"));

    fireEvent(window, new CustomEvent("open-nav-drawer"));

    await waitFor(() => expect(sidebar).not.toHaveAttribute("inert"));
    expect(sidebar).not.toHaveAttribute("aria-hidden");
  });

  it("keeps the desktop sidebar available to keyboard users", async () => {
    mobile = false;
    render(<Sidebar />);
    const sidebar = document.getElementById("dashboard-sidebar")!;

    await waitFor(() => expect(sidebar).not.toHaveAttribute("aria-hidden"));
    expect(sidebar).not.toHaveAttribute("inert");
  });
});

describe("Sidebar plan contrast", () => {
  it("uses full ink for plan labels on the violet surface", async () => {
    mobile = false;
    render(<Sidebar />);
    await screen.findByText("Pro");

    expect(screen.getByText("Plan")).toHaveClass("text-ink");
    expect(screen.getByText("Plan")).not.toHaveClass("text-ink/50");
    expect(screen.getByRole("link", { name: "$5.00 AI credit left" })).toHaveClass("text-ink");
    expect(screen.getByRole("link", { name: "$5.00 AI credit left" })).not.toHaveClass("text-ink/55");
  });
});
