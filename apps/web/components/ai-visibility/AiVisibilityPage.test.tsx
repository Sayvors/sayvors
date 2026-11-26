import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createPrompt: vi.fn(),
  createRun: vi.fn(),
  fetchOverview: vi.fn(),
  fetchPrompts: vi.fn(),
  fetchRuns: vi.fn(),
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
  title: "Visibility check",
  prompt_text: "How visible is Acme Coffee?",
  intent: "visibility",
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
  api.createPrompt.mockResolvedValue(prompt);
  vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
    if (queryKey[1] === "overview") {
      return {
        data: { mention_rate: null, citation_rate: null, recommendation_rate: null },
        isPending: false,
        isError: false,
      } as never;
    }
    if (queryKey[1] === "prompts") {
      return { data: { items: [] }, isPending: false } as never;
    }
    if (queryKey[1] === "runs") {
      return { data: { items: [], total: 0 }, isPending: false } as never;
    }
    return { data: undefined, isPending: true } as never;
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

  it("renders summary metrics while the overview is pending", () => {
    channels.value = [{ id: "branch-1", label: "Acme Coffee" }];
    vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
      if (queryKey[1] === "overview") {
        return { data: undefined, isPending: true, isError: false } as never;
      }
      if (queryKey[1] === "prompts") {
        return { data: { items: [] }, isPending: false } as never;
      }
      if (queryKey[1] === "runs") {
        return { data: { items: [], total: 0 }, isPending: false } as never;
      }
      return { data: undefined, isPending: true } as never;
    });

    render(<AiVisibilityPage />);
    expect(screen.getByLabelText("Evidence coverage")).toHaveAttribute("aria-busy", "true");
  });

  it("shows one clear research action without prompt library clutter", () => {
    channels.value = [{ id: "branch-1", label: "Acme Coffee" }];
    render(<AiVisibilityPage />);

    expect(screen.getByRole("button", { name: "Research my branch" })).toBeInTheDocument();
    expect(screen.queryByText("Prompt library")).not.toBeInTheDocument();
    expect(screen.queryByText("Research history")).not.toBeInTheDocument();
    const overviewCall = vi
      .mocked(useQuery)
      .mock.calls.find(([options]) => options.queryKey[1] === "overview");
    expect(overviewCall?.[0].staleTime).toBe(30_000);
  });

  it("researches the branch with one click using an existing prompt", async () => {
    channels.value = [{ id: "branch-1", label: "Acme Coffee" }];
    vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
      if (queryKey[1] === "overview") {
        return {
          data: { mention_rate: null, citation_rate: null, recommendation_rate: null },
          isPending: false,
          isError: false,
        } as never;
      }
      if (queryKey[1] === "prompts") {
        return { data: { items: [prompt] }, isPending: false } as never;
      }
      if (queryKey[1] === "runs") {
        return { data: { items: [], total: 0 }, isPending: false } as never;
      }
      return { data: undefined, isPending: true } as never;
    });

    render(<AiVisibilityPage />);
    fireEvent.click(screen.getByRole("button", { name: "Research my branch" }));
    await waitFor(() =>
      expect(api.createRun).toHaveBeenCalledWith({
        channel_id: "branch-1",
        prompt_id: "prompt-1",
        depth: "quick",
      }),
    );
    expect(api.createPrompt).not.toHaveBeenCalled();
  });
});
