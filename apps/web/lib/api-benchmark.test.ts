import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-rag", () => ({
  apiFetch: vi.fn(async () => ({})),
}));

import { apiFetch } from "@/lib/api-rag";
import {
  fetchReviewThemes,
  isSavedPlaceReady,
  retryReviewThemes,
  saveBenchmarkPlace,
  searchPlaces,
} from "./api-benchmark";

const api = vi.mocked(apiFetch);

beforeEach(() => {
  api.mockClear();
});

describe("benchmark API client", () => {
  it("passes the Google photo through when saving a place", async () => {
    await saveBenchmarkPlace({
      place_id: "p1",
      label: "Cafe",
      thumbnail: "https://lh3.googleusercontent.com/cover=s256",
    });

    const body = JSON.parse(String(api.mock.calls[0][1]?.body));
    expect(body.thumbnail).toBe("https://lh3.googleusercontent.com/cover=s256");
  });

  it("uses a 30s search timeout instead of the old browser-scraper timeout", async () => {
    await searchPlaces("Wahmy Riyadh");

    expect(api.mock.calls[0][2]).toBe(30_000);
  });
});

describe("review theme API client", () => {
  it("URL-encodes every subject and forwards the abort signal", async () => {
    const controller = new AbortController();

    await fetchReviewThemes(["own:channel/a b", "saved:place&one"], controller.signal);

    expect(api).toHaveBeenCalledWith(
      "/api/v1/benchmark/themes?subjects=own%3Achannel%2Fa%20b&subjects=saved%3Aplace%26one",
      { signal: controller.signal },
    );
  });

  it("posts the exact subject list when retrying failed analyses", async () => {
    const subjects = ["own:mine", "saved:peer"];

    await retryReviewThemes(subjects);

    expect(api).toHaveBeenCalledWith("/api/v1/benchmark/themes/retry", {
      method: "POST",
      body: JSON.stringify({ subjects }),
    });
  });
});

describe("saved card readiness", () => {
  it("is ready when search supplied metadata even before fetched_at exists", () => {
    expect(isSavedPlaceReady({
      details_ready: true,
      fetched_at: null,
      last_scrape_error: null,
    })).toBe(true);
  });

  it("is not ready after a scrape error", () => {
    expect(isSavedPlaceReady({
      details_ready: true,
      fetched_at: "2026-11-24T00:00:00Z",
      last_scrape_error: "blocked",
    })).toBe(false);
  });

  it("falls back to fetched_at for older API responses", () => {
    expect(isSavedPlaceReady({
      fetched_at: "2026-11-24T00:00:00Z",
      last_scrape_error: null,
    })).toBe(true);
    expect(isSavedPlaceReady({
      fetched_at: null,
      last_scrape_error: null,
    })).toBe(false);
  });
});
