import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  startQuerySet: vi.fn(),
  fetchLatestQuerySet: vi.fn(),
  fetchRun: vi.fn(),
  retryRun: vi.fn(),
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

const latestData = {
  query_set: {
    id: "qs-1",
    channel_id: "branch-1",
    version: 1,
    parent_query_set_id: null,
    status: "completed",
    phase: "complete",
    depth: "quick",
    job_id: "job-1",
    classification: { industry: "recruitment", business_type: "recruitment", confidence: 0.9, uncertainties: [] },
    total_questions: 1,
    completed_questions: 1,
    failed_questions: 0,
    failure_code: null,
    error: null,
    started_at: "2026-11-26T10:00:00Z",
    completed_at: "2026-11-26T10:01:00Z",
    created_at: "2026-11-26T10:00:00Z",
    updated_at: "2026-11-26T10:01:00Z",
  },
  questions: [
    {
      id: "question-1",
      query_set_id: "qs-1",
      version: 1,
      question_key: "q001",
      question_text: "Is Sayvors licensed in Makkah?",
      language: "en",
      customer_intent: "licensing",
      industry_relevance: 90,
      service_relevance: 95,
      geographic_context: "Makkah",
      business_relevance_score: 92,
      research_priority: "P1",
      origin: "initial",
      status: "completed",
      run_id: "run-1",
      mentioned: true,
      cited: true,
      recommended: false,
      incorrect: false,
    },
  ],
  versions: [
    { id: "qs-1", version: 1, status: "completed", total_questions: 1, completed_questions: 1, failed_questions: 0, created_at: "2026-11-26T10:00:00Z", completed_at: "2026-11-26T10:01:00Z" },
  ],
  metrics: {
    completed_runs: 1,
    mention_rate: 100,
    citation_rate: 100,
    recommendation_rate: 0,
    source_count: 2,
    validated_claim_count: 1,
  },
  coverage: {
    third_party_source_count: 2,
    owned_source_count: 0,
    validated_claim_count: 1,
    metrics: { platforms_found: 0 },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  channels.value = [];
  query.invalidateQueries.mockResolvedValue(undefined);
  api.fetchLatestQuerySet.mockResolvedValue(latestData);
  api.startQuerySet.mockResolvedValue({ id: "qs-2", status: "generating" });
  vi.mocked(useQuery).mockReturnValue({
    data: latestData,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
});

describe("AiVisibilityPage", () => {
  it("asks for a connected branch when none exists", () => {
    render(<AiVisibilityPage />);
    expect(screen.getByText(/Connect a Google location/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect a location" })).toHaveAttribute("href", "/dashboard/locations");
  });

  it("shows the empty state when no research exists", () => {
    channels.value = [{ id: "branch-1", label: "Sayvors Branch" }];
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error("query_set_not_found"),
      refetch: vi.fn(),
    } as never);
    render(<AiVisibilityPage />);
    expect(screen.getByText("No research yet")).toBeInTheDocument();
  });

  it("starts background research with one click and never creates a fixed prompt", async () => {
    channels.value = [{ id: "branch-1", label: "Sayvors Branch" }];
    render(<AiVisibilityPage />);
    fireEvent.click(screen.getByRole("button", { name: "Research my branch" }));
    await waitFor(() =>
      expect(api.startQuerySet).toHaveBeenCalledWith({ channel_id: "branch-1", depth: "quick" }),
    );
    await waitFor(() => expect(query.invalidateQueries).toHaveBeenCalled());
    expect(screen.queryByText("Prompt library")).not.toBeInTheDocument();
  });

  it("shows a non-blocking background banner while the set is running", () => {
    channels.value = [{ id: "branch-1", label: "Sayvors Branch" }];
    const running = {
      ...latestData,
      query_set: { ...latestData.query_set, status: "running", phase: "researching", completed_questions: 0, completed_at: null },
      questions: [],
      metrics: { ...latestData.metrics, completed_runs: 0, mention_rate: null, citation_rate: null, recommendation_rate: null },
    };
    vi.mocked(useQuery).mockReturnValue({ data: running, isPending: false, isError: false } as never);
    render(<AiVisibilityPage />);
    expect(screen.getByText("Research in progress")).toBeInTheDocument();
    expect(screen.getByText(/You can leave this page and come back later/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Research activity")).not.toBeInTheDocument();
  });

  it("renders owner-first cards, intent chart, and customer question results", () => {
    channels.value = [{ id: "branch-1", label: "Sayvors Branch" }];
    render(<AiVisibilityPage />);
    expect(screen.getByLabelText("Public visibility")).toBeInTheDocument();
    expect(screen.getByLabelText("Customer intent coverage")).toBeInTheDocument();
    expect(screen.getByText("Is Sayvors licensed in Makkah?")).toBeInTheDocument();
    expect(screen.queryByText("Prompt library")).not.toBeInTheDocument();
  });
});
