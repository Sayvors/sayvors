import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import ComparePicker from "./ComparePicker";
import { useI18n } from "@/lib/i18n/I18nProvider";
import en from "@/lib/i18n/en";
import type { CompareChannelOption } from "@/lib/benchmark-selection";

vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  return { ...actual, useI18n: vi.fn(actual.useI18n) };
});

const own: CompareChannelOption[] = [
  {
    id: "unverified",
    display_name: "Alpha Branch",
    platform: "google_reviews",
    status: "active",
    verification_status: "pending",
    verified: false,
  },
  {
    id: "verified",
    display_name: "Zulu Branch",
    platform: "google_reviews",
    status: "active",
    verification_status: "verified",
    verified: true,
  },
];

beforeEach(() => {
  vi.mocked(useI18n).mockReturnValue({ locale: "en", dir: "ltr", t: en, setLocale: vi.fn() });
});

describe("ComparePicker verification", () => {
  it("lists verified branches first and labels both verification states", () => {
    render(
      <ComparePicker
        selection={{ main: null, competitors: [] }}
        onChange={vi.fn()}
        saved={[]}
        own={own}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Select a business…" })[0]);

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    expect(within(checkboxes[0].closest("label")!).getByText("Zulu Branch")).toBeInTheDocument();
    expect(within(checkboxes[0].closest("label")!).getByText("Verified")).toBeInTheDocument();
    expect(within(checkboxes[1].closest("label")!).getByText("Alpha Branch")).toBeInTheDocument();
    expect(within(checkboxes[1].closest("label")!).getByText("Unverified")).toBeInTheDocument();
  });
});
