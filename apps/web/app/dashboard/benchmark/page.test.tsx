import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  deleteBenchmarkPlace: vi.fn(),
  fetchSavedPlaces: vi.fn(),
  refreshBenchmarkPlace: vi.fn(),
  saveBenchmarkPlace: vi.fn(),
  searchPlaces: vi.fn(),
  setBenchmarkHeatmap: vi.fn(),
  setBenchmarkSet: vi.fn(),
}));

const query = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
  refetch: vi.fn(),
}));

vi.mock("@/lib/api-benchmark", () => ({
  ...api,
  isSavedPlaceReady: (place: { details_ready?: boolean; fetched_at: string | null; last_scrape_error: string | null }) =>
    !place.last_scrape_error && (place.details_ready ?? Boolean(place.fetched_at)),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
  useQueryClient: () => ({ invalidateQueries: query.invalidateQueries }),
}));

vi.mock("@/components/benchmark/HeatmapGrid", () => ({ default: () => null }));
vi.mock("@/components/benchmark/OwnLocations", () => ({ default: () => null }));

vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  const en = await vi.importActual<typeof import("@/lib/i18n/en")>("@/lib/i18n/en");
  return { ...actual, useI18n: () => ({ locale: "en", dir: "ltr", t: en.default }) };
});

import { useQuery } from "@tanstack/react-query";
import BenchmarkPage from "./page";
import type { PlaceResult, SavedPlace } from "@/lib/api-benchmark";

const searchResult: PlaceResult = {
  place_id: "peer-1",
  name: "Rival Cafe",
  address: "Riyadh",
  rating: 4.5,
  review_count: 100,
  latitude: 24.7,
  longitude: 46.7,
  types: ["cafe"],
  maps_url: "https://maps.google.com/?cid=1",
};

function savedPlace(over: Partial<SavedPlace> = {}): SavedPlace {
  return {
    id: "saved-1",
    place_id: "peer-1",
    label: "Rival Cafe",
    notes: null,
    name: "Rival Cafe",
    address: "Riyadh",
    rating: 4.5,
    review_count: 100,
    latitude: 24.7,
    longitude: 46.7,
    in_heatmap: true,
    in_bench_set: true,
    fetched_at: "2026-11-24T00:00:00Z",
    details_ready: true,
    last_scrape_error: null,
    created_at: "2026-11-20T00:00:00Z",
    ...over,
  };
}

function mockSaved(places: SavedPlace[]) {
  vi.mocked(useQuery).mockReturnValue({
    data: places,
    isPending: false,
    isError: false,
    refetch: query.refetch,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  query.invalidateQueries.mockResolvedValue(undefined);
  query.refetch.mockResolvedValue(undefined);
  api.fetchSavedPlaces.mockResolvedValue([]);
  api.searchPlaces.mockResolvedValue({
    query: "cafe",
    location: {},
    nearby: [searchResult],
    other: [],
  });
  mockSaved([]);
});

async function searchAndOpenSave() {
  fireEvent.change(screen.getByRole("textbox", { name: "Search businesses" }), { target: { value: "cafe" } });
  fireEvent.click(screen.getByRole("button", { name: "Search businesses" }));
  await screen.findByRole("button", { name: "Save" });
}

describe("benchmark mutation errors", () => {
  it("keeps search results visible and offers retry when saving fails", async () => {
    api.saveBenchmarkPlace.mockRejectedValueOnce(new Error("Save blocked"));
    render(<BenchmarkPage />);
    await searchAndOpenSave();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Save blocked");
    expect(screen.getByText("Rival Cafe")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(query.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["benchmark", "saved"] });
  });

  it("surfaces heatmap toggle failures", async () => {
    mockSaved([savedPlace()]);
    api.setBenchmarkHeatmap.mockRejectedValueOnce(new Error("Heatmap blocked"));
    render(<BenchmarkPage />);

    fireEvent.click(screen.getByRole("button", { name: "Actions for Rival Cafe" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove from heatmap" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Heatmap blocked");
  });

  it("surfaces benchmark-set failures", async () => {
    mockSaved([savedPlace()]);
    api.setBenchmarkSet.mockRejectedValueOnce(new Error("Set blocked"));
    render(<BenchmarkPage />);

    fireEvent.click(screen.getByRole("button", { name: "In benchmark set" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Set blocked");
  });

  it("surfaces remove failures", async () => {
    mockSaved([savedPlace()]);
    api.deleteBenchmarkPlace.mockRejectedValueOnce(new Error("Remove blocked"));
    render(<BenchmarkPage />);

    fireEvent.click(screen.getByRole("button", { name: "Actions for Rival Cafe" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove from bench" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Remove blocked");
  });

  it("surfaces refresh failures and clears the busy state", async () => {
    mockSaved([savedPlace({ details_ready: false, fetched_at: null })]);
    api.refreshBenchmarkPlace.mockRejectedValueOnce(new Error("Refresh blocked"));
    render(<BenchmarkPage />);

    fireEvent.click(screen.getByRole("button", { name: "Actions for Rival Cafe" }));
    fireEvent.click(screen.getByRole("button", { name: "Fetch details" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Refresh blocked");
    expect(screen.queryByText("Collecting recent reviews…")).not.toBeInTheDocument();
  });
});
