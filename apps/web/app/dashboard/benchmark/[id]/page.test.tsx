import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "ChIJ-demo" }),
  useRouter: () => ({ replace }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: undefined, isPending: true }),
}));

vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  const en = await vi.importActual<typeof import("@/lib/i18n/en")>("@/lib/i18n/en");
  return { ...actual, useI18n: () => ({ locale: "en", dir: "ltr", t: en.default }) };
});

import BenchmarkDetailPage from "./page";

beforeEach(() => {
  replace.mockClear();
});

describe("legacy benchmark detail route", () => {
  it("redirects into Compare with the saved place selected", () => {
    render(<BenchmarkDetailPage />);

    expect(replace).toHaveBeenCalledWith(
      "/dashboard/benchmark/compare?main=saved%3AChIJ-demo",
      { scroll: false },
    );
  });
});
