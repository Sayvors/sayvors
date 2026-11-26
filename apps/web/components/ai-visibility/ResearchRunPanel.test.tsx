import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchRun: vi.fn(),
  retryRun: vi.fn(),
}));

vi.mock("@/lib/api-ai-visibility", () => api);
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
  keepPreviousData: vi.fn(),
}));
vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  const en = await vi.importActual<typeof import("@/lib/i18n/en")>("@/lib/i18n/en");
  return { ...actual, useI18n: () => ({ locale: "en", dir: "ltr", t: en.default }) };
});

import { useQuery } from "@tanstack/react-query";
import en from "@/lib/i18n/en";
import ResearchRunPanel from "./ResearchRunPanel";

const failedRun = {
  id: "run-old",
  status: "failed",
  error: "temporary failure",
  evidence_coverage: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useQuery).mockReturnValue({
    data: failedRun,
    isPending: false,
    isError: false,
  } as never);
  api.retryRun.mockResolvedValue({ id: "run-new", status: "queued" });
});

describe("ResearchRunPanel retry", () => {
  it("selects the new run returned by the retry endpoint", async () => {
    const onRetry = vi.fn();
    render(
      <ResearchRunPanel
        runId="run-old"
        copy={en.aiVisibility}
        onRetry={onRetry}
      />,
    );

    expect(screen.queryByLabelText(en.aiVisibility.activityTitle)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: en.aiVisibility.retry }));
    await waitFor(() => expect(api.retryRun).toHaveBeenCalledWith("run-old"));
    await waitFor(() => expect(onRetry).toHaveBeenCalledWith("run-new"));
  });
});
