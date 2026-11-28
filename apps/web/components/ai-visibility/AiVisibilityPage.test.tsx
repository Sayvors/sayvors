import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
vi.mock("./ResearchRunPanel", () => ({
  default: ({ runId }: { runId: string }) => <div>Brief for {runId}</div>,
}));
vi.mock("@/components/analytics/Controls", () => ({
  useGoogleChannels: () => channels.value,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
  useQueryClient: () => query,
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

  it("opens a question brief in a modal and restores focus when closed", () => {
    channels.value = [{ id: "branch-1", label: "Sayvors Branch" }];
    render(<AiVisibilityPage />);
    const trigger = screen.getByRole("button", { name: /Is Sayvors licensed/ });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Brief for run-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("labels the action as resume when a partial set has pending questions", () => {
    channels.value = [{ id: "branch-1", label: "Sayvors Branch" }];
    const partial = {
      ...latestData,
      query_set: { ...latestData.query_set, status: "partial", completed_questions: 0 },
      questions: [{ ...latestData.questions[0], status: "pending", run_id: null, mentioned: null, cited: null }],
    };
    vi.mocked(useQuery).mockReturnValue({ data: partial, isPending: false, isError: false } as never);
    render(<AiVisibilityPage />);
    expect(screen.getByRole("button", { name: "Resume research" })).toBeInTheDocument();
  });

  it("shows an all-locations aggregate without starting branch research", () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    const aggregate = [
      { channel: channels.value[0], data: latestData, error: null },
      { channel: channels.value[1], data: {
        ...latestData,
        query_set: { ...latestData.query_set, id: "qs-2", channel_id: "branch-2" },
        questions: [{ ...latestData.questions[0], id: "question-2", query_set_id: "qs-2" }],
      }, error: null },
    ];
    vi.mocked(useQuery).mockReturnValue({ data: aggregate, isPending: false, isError: false } as never);
    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });
    expect(screen.getByRole("heading", { name: "All locations" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Combined customer questions across all connected branches.")).toBeInTheDocument();
    expect(screen.getAllByText("Makkah Branch").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Jeddah Branch").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Select a branch to research" })).toBeDisabled();
  });

  it("shows loading instead of an empty state while all-locations research is pending", () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });

    expect(screen.getByRole("status", { name: "Loading research…" })).toBeInTheDocument();
    expect(screen.queryByText("No research yet")).not.toBeInTheDocument();
  });

  it("renders a retryable error when every all-locations branch fails to load", () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    const refetch = vi.fn();
    vi.mocked(useQuery).mockReturnValue({
      data: channels.value.map((channel) => ({
        channel,
        data: null,
        error: new Error("Network unavailable"),
      })),
      isPending: false,
      isError: false,
      error: null,
      refetch,
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Could not load research.");
    expect(screen.queryByText("No research yet")).not.toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("shows the all-locations empty state only when every branch has no query set", () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    vi.mocked(useQuery).mockReturnValue({
      data: channels.value.map((channel) => ({
        channel,
        data: null,
        error: new Error("query_set_not_found"),
      })),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });

    expect(screen.getByText("No research yet")).toBeInTheDocument();
    expect(screen.getByText("No connected branch has completed research yet.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps successful aggregate data visible alongside a retryable partial failure", () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    const refetch = vi.fn();
    vi.mocked(useQuery).mockReturnValue({
      data: [
        { channel: channels.value[0], data: latestData, error: null },
        { channel: channels.value[1], data: null, error: new Error("Network unavailable") },
      ],
      isPending: false,
      isError: false,
      error: null,
      refetch,
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Some locations could not be loaded. Results are incomplete.");
    expect(screen.getByRole("region", { name: "Evidence coverage" })).toBeInTheDocument();
    expect(screen.getAllByText("Makkah Branch").length).toBeGreaterThan(0);
    expect(screen.getByText("Is Sayvors licensed in Makkah?")).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("preserves each branch error in the all-locations query result", async () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    const branchError = new Error("Jeddah is unavailable");
    api.fetchLatestQuerySet.mockImplementation((channelId: string) =>
      channelId === "branch-1"
        ? Promise.resolve(latestData)
        : Promise.reject(branchError),
    );
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });
    const options = vi.mocked(useQuery).mock.calls.at(-1)![0];
    const queryFn = options.queryFn as (context: unknown) => Promise<unknown>;
    const rows = await queryFn({}) as Array<{
      channel: { id: string };
      data: unknown;
      error: unknown;
    }>;

    expect(rows[0]).toMatchObject({ channel: { id: "branch-1" }, data: latestData, error: null });
    expect(rows[1]).toMatchObject({ channel: { id: "branch-2" }, data: null, error: branchError });
  });

  it("retains branch labels in aggregate question rows and modal context", () => {
    channels.value = [
      { id: "branch-1", label: "Makkah Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    vi.mocked(useQuery).mockReturnValue({
      data: [
        { channel: channels.value[0], data: latestData, error: null },
        {
          channel: channels.value[1],
          data: {
            ...latestData,
            query_set: { ...latestData.query_set, id: "qs-2", channel_id: "branch-2" },
            questions: [{
              ...latestData.questions[0],
              id: "question-2",
              query_set_id: "qs-2",
              question_text: "Does Sayvors serve Jeddah?",
              run_id: "run-2",
            }],
          },
          error: null,
        },
      ],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });

    const makkahQuestion = screen.getByRole("button", { name: /Is Sayvors licensed/ });
    expect(within(makkahQuestion).getByText("Makkah Branch")).toBeInTheDocument();
    const jeddahQuestion = screen.getByRole("button", { name: /Does Sayvors serve Jeddah/ });
    expect(within(jeddahQuestion).getByText("Jeddah Branch")).toBeInTheDocument();
    fireEvent.click(jeddahQuestion);
    expect(screen.getByRole("dialog", { name: "Decision brief" })).toHaveAccessibleDescription(
      "Jeddah Branch · Does Sayvors serve Jeddah?",
    );
  });

  it("localizes all-locations branch-card status values", () => {
    channels.value = [{ id: "branch-1", label: "Makkah Branch" }];
    vi.mocked(useQuery).mockReturnValue({
      data: [{
        channel: channels.value[0],
        data: {
          ...latestData,
          query_set: { ...latestData.query_set, status: "partial" },
        },
        error: null,
      }],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    render(<AiVisibilityPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "all" },
    });

    expect(screen.getByText(/Version 1 · Some questions could not be researched/)).toBeInTheDocument();
    expect(screen.queryByText("partial")).not.toBeInTheDocument();
  });

  it("does not render previous-branch data after switching branches", () => {
    channels.value = [
      { id: "branch-1", label: "Sayvors Branch" },
      { id: "branch-2", label: "Jeddah Branch" },
    ];
    vi.mocked(useQuery).mockReturnValue({
      data: latestData,
      isPending: false,
      isError: false,
      isPlaceholderData: true,
      refetch: vi.fn(),
    } as never);

    render(<AiVisibilityPage />);
    expect(screen.getByText("Is Sayvors licensed in Makkah?")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Branch" }), {
      target: { value: "branch-2" },
    });

    expect(screen.getByRole("combobox", { name: "Branch" })).toHaveValue("branch-2");
    expect(screen.queryByText("Is Sayvors licensed in Makkah?")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Evidence coverage")).not.toBeInTheDocument();
    expect(screen.queryAllByText("recruitment")).toHaveLength(0);
  });
});
