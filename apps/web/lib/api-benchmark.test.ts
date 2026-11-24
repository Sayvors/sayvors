import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-rag", () => ({
  apiFetch: vi.fn(async () => ({})),
}));

import { apiFetch } from "@/lib/api-rag";
import { isSavedPlaceReady, saveBenchmarkPlace, searchPlaces } from "./api-benchmark";

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
