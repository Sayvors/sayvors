import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchRuns: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
  retryRun: vi.fn(),
}));
vi.mock("@/lib/api-ai-visibility", () => api);
vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  const en = await vi.importActual<typeof import("@/lib/i18n/en")>("@/lib/i18n/en");
  return { ...actual, useI18n: () => ({ t: en.default, locale: "en", dir: "ltr" }) };
});

import RunHistory from "./RunHistory";

const copy = {
  history: "Research history",
  noRuns: "No research runs yet.",
  retry: "Retry",
  deleteRun: "Delete run",
  confirmDelete: "Delete this run?",
  comparePrevious: "Compare",
  stages: { completed: "Completed", failed: "Failed" },
  loading: "Loading",
  loadError: "Could not load",
  mentioned: "Mentioned",
  cited: "Cited",
  all: "All",
  cancel: "Cancel",
};

function renderHistory(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchRuns.mockResolvedValue({ items: [], total: 0 });
});

describe("RunHistory", () => {
  it("renders the empty state", async () => {
    renderHistory(
      <RunHistory
        channelId="branch-1"
        selectedId={null}
        copy={copy as never}
        onSelect={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByText("No research runs yet.")).toBeInTheDocument();
  });

  it("confirms before deleting", async () => {
    api.fetchRuns.mockResolvedValue({
      items: [
        {
          id: "run-1",
          prompt_id: "prompt-1",
          prompt_title: "Coffee",
          status: "completed",
          mentioned: true,
          cited: true,
          recommended: true,
          incorrect: false,
          source_count: 2,
          validation_status: "passed",
          created_at: "2026-11-25T00:00:00Z",
          completed_at: "2026-11-25T00:01:00Z",
        },
      ],
      total: 1,
    });
    const onChanged = vi.fn();
    renderHistory(
      <RunHistory
        channelId="branch-1"
        selectedId="run-1"
        copy={copy as never}
        onSelect={vi.fn()}
        onChanged={onChanged}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Delete this run?")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete run" }));
    await waitFor(() => expect(api.deleteRun).toHaveBeenCalledWith("run-1"));
    expect(onChanged).toHaveBeenCalled();
  });
});
