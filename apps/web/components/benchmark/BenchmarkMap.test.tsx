/* eslint-disable @typescript-eslint/no-explicit-any */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { loadGoogleMaps } = vi.hoisted(() => ({ loadGoogleMaps: vi.fn() }));
vi.mock("@/lib/google-maps", () => ({ loadGoogleMaps }));

import BenchmarkMap from "./BenchmarkMap";
import type { SavedPlace } from "@/lib/api-benchmark";

function place(id: string, lat: number | null, lng: number | null, reviews = 10): SavedPlace {
  return {
    id,
    place_id: id,
    label: `Business ${id}`,
    notes: null,
    name: `Business ${id}`,
    rating: 4.5,
    review_count: reviews,
    latitude: lat,
    longitude: lng,
    in_heatmap: true,
    in_bench_set: false,
    fetched_at: null,
    last_scrape_error: null,
    created_at: null,
  };
}

const maps = {
  Map: vi.fn(function () {
    return { fitBounds: vi.fn(), setCenter: vi.fn(), setZoom: vi.fn() };
  }),
  Marker: vi.fn(function () {
    return { setMap: vi.fn(), addListener: vi.fn() };
  }),
  LatLng: vi.fn(function (lat: number, lng: number) {
    return { lat, lng };
  }),
  LatLngBounds: vi.fn(function () {
    return { extend: vi.fn() };
  }),
  InfoWindow: vi.fn(function () {
    return { open: vi.fn(), setContent: vi.fn() };
  }),
  visualization: {
    HeatmapLayer: vi.fn(function () {
      return { setMap: vi.fn() };
    }),
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  loadGoogleMaps.mockResolvedValue(undefined);
  (window as any).google = { maps };
});

describe("BenchmarkMap", () => {
  it("renders an explicit setup message when no API key is configured", () => {
    render(<BenchmarkMap places={[place("a", 24.7, 46.7)]} apiKey="" />);

    expect(screen.getByText(/NEXT_PUBLIC_GOOGLE_MAPS_API_KEY/)).toBeInTheDocument();
    expect(loadGoogleMaps).not.toHaveBeenCalled();
  });

  it("does not invent coordinates for unlocated businesses", () => {
    render(<BenchmarkMap places={[place("a", null, null)]} apiKey="test-key" />);

    expect(screen.getByText(/No mapped locations/)).toBeInTheDocument();
    expect(loadGoogleMaps).not.toHaveBeenCalled();
  });

  it("renders markers and review-weighted density, then cleans them up", async () => {
    const { unmount } = render(
      <BenchmarkMap
        places={[place("a", 24.7, 46.7, 12), place("b", 24.8, 46.8, 120)]}
        apiKey="test-key"
      />,
    );

    await waitFor(() => expect(maps.Map).toHaveBeenCalledOnce());
    expect(maps.Marker).toHaveBeenCalledTimes(2);
    expect(maps.visualization.HeatmapLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        data: [
          expect.objectContaining({ weight: 12 }),
          expect.objectContaining({ weight: 120 }),
        ],
      }),
    );

    const markerInstances = maps.Marker.mock.results.map((result) => result.value);
    const heatmap = maps.visualization.HeatmapLayer.mock.results[0].value;
    unmount();
    markerInstances.forEach((marker) => expect(marker.setMap).toHaveBeenCalledWith(null));
    expect(heatmap.setMap).toHaveBeenCalledWith(null);
  });

  it("opens a business info window without injecting untrusted HTML", async () => {
    render(
      <BenchmarkMap
        places={[place("<script>", 24.7, 46.7)]}
        apiKey="test-key"
      />,
    );

    await waitFor(() => expect(maps.Marker).toHaveBeenCalledOnce());
    const marker = maps.Marker.mock.results[0].value;
    const listener = marker.addListener.mock.calls[0];
    expect(listener[0]).toBe("click");
    listener[1]();

    const info = maps.InfoWindow.mock.results[0].value;
    expect(info.open).toHaveBeenCalled();
    const content = info.setContent.mock.calls[0][0] as HTMLElement;
    expect(content.querySelector("script")).toBeNull();
    expect(content.textContent).toContain("Business <script>");
  });

  it("shows a retryable loader error", async () => {
    loadGoogleMaps.mockRejectedValueOnce(new Error("blocked"));
    const onRetry = vi.fn();
    render(
      <BenchmarkMap
        places={[place("a", 24.7, 46.7)]}
        apiKey="test-key"
        onRetry={onRetry}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load Google Maps.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
