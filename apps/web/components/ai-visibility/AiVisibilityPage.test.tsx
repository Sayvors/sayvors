import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createPrompt: vi.fn(),
  createRun: vi.fn(),
  deletePrompt: vi.fn(),
  fetchOverview: vi.fn(),
  fetchPrompts: vi.fn(),
  fetchRuns: vi.fn(),
  updatePrompt: vi.fn(),
}));
const channels = vi.hoisted(() => ({ value: [] as Array<{ id: string; label: string }> }));
const query = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));

vi.mock("@/lib/api-ai-visibility", () => api);
vi.mock("@/components/analytics/Controls", () => ({
  useGoogleChannels: () => channels.value,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
  useQueryClient: () => query,
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
import AiVisibilityPage from "./AiVisibilityPage";

const prompt = {
  id: "prompt-1",
  channel_id: "branch-1",
  title: "Coffee",
  prompt_text: "Best coffee near Malqa",
  intent: "discovery",
  is_active: true,
  created_at: "2026-11-25T00:00:00Z",
  updated_at: "2026-11-25T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  channels.value = [];
  query.invalidateQueries.mockResolvedValue(undefined);
  api.fetchOverview.mockResolvedValue({
    completed_runs: 0,
    mention_rate: null,
    citation_rate: null,
    recommendation_rate: null,
    active_prompts: 0,
    covered_prompts: 0,
    prompt_coverage: null,
    failed_runs: 0,
    insufficient_runs: 0,
    source_count: 0,
    validated_claim_count: 0,
  });
  api.fetchPrompts.mockResolvedValue({ items: [] });
  api.fetchRuns.mockResolvedValue({ items: [], total: 0 });
  api.createRun.mockResolvedValue({ id: "run-1", status: "queued" });
  vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
    if (queryKey[1] === "overview") {
      return {
        data: { mention_rate: null, citation_rate: null, recommendation_rate: null },
      } as never;
    }
    if (queryKey[1] === "prompts") {
      return { data: { items: [] } } as never;
    }
    if (queryKey[1] === "run") {
      return { data: undefined, isPending: true } as never;
    }
    return { data: { items: [] } } as never;
  });
});

describe("AiVisibilityPage", () => {
  it("asks for a connected branch when none exists", () => {
    render(<AiVisibilityPage />);
    expect(screen.getByText(/Connect a Google location/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect a location" })).toHaveAttribute(
      "href",
      "/dashboard/locations",
    );
  });

  it("renders missing summary metrics while the overview is pending", () => {
    channels.value = [{ id: "branch-1", label: "Acme Coffee" }];
    vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
      if (queryKey[1] === "overview") {
        return { data: undefined, isPending: true } as never;
      }
      if (queryKey[1] === "prompts") {
        return { data: { items: [] } } as never;
      }
      if (queryKey[1] === "run") {
        return { data: undefined, isPending: true } as never;
      }
      return { data: { items: [] } } as never;
    });

    render(<AiVisibilityPage />);
    expect(screen.getByLabelText("Evidence coverage")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.queryByText("100.0%")).not.toBeInTheDocument();
  });

  it("shows result-first disclosures and keeps query data fresh", () => {
    channels.value = [{ id: "branch-1", label: "Acme Coffee" }];
    render(<AiVisibilityPage />);

    expect(screen.getAllByText("Prompt library").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Research history").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Branch")).toHaveAttribute("title");
    const overviewCall = vi
      .mocked(useQuery)
      .mock.calls.find(([options]) => options.queryKey[1] === "overview");
    expect(overviewCall?.[0].staleTime).toBe(30_000);
  });

  it("runs the selected prompt for the selected branch", async () => {
    channels.value = [{ id: "branch-1", label: "Acme Coffee" }];
    api.fetchPrompts.mockResolvedValue({ items: [prompt] });
    vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
      if (queryKey[1] === "overview") {
        return { data: { mention_rate: null, citation_rate: null, recommendation_rate: null } } as never;
      }
      if (queryKey[1] === "prompts") {
        return { data: { items: [prompt] } } as never;
      }
      if (queryKey[1] === "run") {
        return { data: undefined, isPending: true } as never;
      }
      return { data: { items: [] } } as never;
    });

    render(<AiVisibilityPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Coffee/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find with proof" }));
    await waitFor(() =>
      expect(api.createRun).toHaveBeenCalledWith({
        channel_id: "branch-1",
        prompt_id: "prompt-1",
        depth: "quick",
      }),
    );
  });
});
