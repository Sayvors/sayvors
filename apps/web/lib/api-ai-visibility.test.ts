import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-rag", () => ({ apiFetch: fetchMock }));

import {
  createPrompt,
  createRun,
  deletePrompt,
  deleteRun,
  fetchOverview,
  fetchPrompts,
  fetchRun,
  fetchRuns,
  fetchLatestQuerySet,
  retryRun,
  startQuerySet,
  updatePrompt,
} from "./api-ai-visibility";

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({});
});

describe("AI visibility API", () => {
  it("uses tenant-scoped endpoints and query params", async () => {
    await fetchOverview("branch-1", 30);
    await fetchPrompts("branch-1", true);
    await fetchRuns("branch-1", {
      status: "completed",
      promptId: "prompt-1",
      limit: 25,
      offset: 0,
    });
    await fetchRun("run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/ai-visibility/overview?channel_id=branch-1&days=30",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/ai-visibility/prompts?channel_id=branch-1&include_archived=true",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/v1/ai-visibility/runs?channel_id=branch-1&status=completed&prompt_id=prompt-1&limit=25&offset=0",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/v1/ai-visibility/runs/run-1",
    );
  });

  it("omits unset filters and encodes values", async () => {
    await fetchRuns("branch / 1");
    await fetchOverview("branch / 1", 30);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/ai-visibility/runs?channel_id=branch+%2F+1",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/ai-visibility/overview?channel_id=branch+%2F+1&days=30",
    );
  });

  it("starts background query sets and reads the latest aggregate", async () => {
    await startQuerySet({ channel_id: "branch-1", depth: "quick" });
    await fetchLatestQuerySet("branch / 1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/ai-visibility/query-sets", {
      method: "POST",
      body: JSON.stringify({ channel_id: "branch-1", depth: "quick" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/ai-visibility/query-sets/latest?channel_id=branch+%2F+1",
    );
  });

  it("posts prompts and runs with JSON bodies", async () => {    const prompt = {
      channel_id: "branch-1",
      title: "Coffee",
      prompt_text: "Best coffee near Malqa",
      intent: "discovery",
    };
    await createPrompt(prompt);
    await createRun({ channel_id: "branch-1", prompt_id: "prompt-1" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/ai-visibility/prompts", {
      method: "POST",
      body: JSON.stringify(prompt),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/ai-visibility/runs", {
      method: "POST",
      body: JSON.stringify({ channel_id: "branch-1", prompt_id: "prompt-1" }),
    });
  });

  it("uses the expected methods for mutations and encoded resource ids", async () => {
    await updatePrompt("prompt / 1", { title: "Local coffee", is_active: false });
    await deletePrompt("prompt / 1");
    await retryRun("run / 1");
    await deleteRun("run / 1");
    await fetchRun("run / 1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/ai-visibility/prompts/prompt%20%2F%201",
      {
        method: "PATCH",
        body: JSON.stringify({ title: "Local coffee", is_active: false }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/ai-visibility/prompts/prompt%20%2F%201",
      { method: "DELETE" },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/v1/ai-visibility/runs/run%20%2F%201/retry",
      { method: "POST" },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/v1/ai-visibility/runs/run%20%2F%201",
      { method: "DELETE" },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/v1/ai-visibility/runs/run%20%2F%201",
    );
  });
});
