import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TrendChart from "./TrendChart";
import { buildTrendSeries, sharedTimeDomain } from "@/lib/benchmark-trend";
import type { SubjectHistory } from "@/lib/api-benchmark";

const history: SubjectHistory[] = [
  {
    key: "own:mine",
    kind: "own",
    name: "Your Branch",
    points: [
      { at: "2026-10-01T00:00:00Z", rating: 4.5, reviews: 10 },
      { at: "2026-10-15T00:00:00Z", rating: 4.7, reviews: 14 },
      { at: "2026-11-01T00:00:00Z", rating: 4.8, reviews: 18 },
    ],
  },
  {
    key: "saved:peer",
    kind: "saved",
    name: "Competitor",
    points: [
      { at: "2026-10-01T00:00:00Z", rating: 4.2, reviews: 20 },
      { at: "2026-10-15T00:00:00Z", rating: 4.3, reviews: 24 },
      { at: "2026-11-01T00:00:00Z", rating: 4.4, reviews: 30 },
    ],
  },
];

describe("benchmark trend data", () => {
  it("builds cumulative review growth rather than noisy interval velocity", () => {
    const series = buildTrendSeries(history, "reviews");
    expect(series.find((row) => row.key === "own:mine")?.points.map((p) => p.value)).toEqual([10, 14, 18]);
  });

  it("shares one date domain across every series", () => {
    const domain = sharedTimeDomain([
      ...buildTrendSeries(history, "rating"),
      ...buildTrendSeries(history, "reviews"),
    ]);
    expect(domain.start).toBe(new Date("2026-10-01T00:00:00Z").getTime());
    expect(domain.end).toBe(new Date("2026-11-01T00:00:00Z").getTime());
  });
});

describe("TrendChart", () => {
  it("renders rating and cumulative review growth panels", () => {
    const { container } = render(
      <TrendChart history={history} title="Where is it heading?" mainKey="own:mine" />,
    );

    expect(screen.getByRole("heading", { name: "Where is it heading?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Average rating" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review growth" })).toBeInTheDocument();
    expect(
      container.querySelector('polyline[data-chart="reviews"][data-own="true"]'),
    ).toBeInTheDocument();
  });

  it("emphasizes the selected branch without relying on color alone", () => {
    const { container } = render(
      <TrendChart history={history} title="Where is it heading?" mainKey="own:mine" />,
    );

    const ownLine = container.querySelector('polyline[data-chart="rating"][data-own="true"]');
    expect(ownLine).toHaveAttribute("stroke-width", "3");
    expect(ownLine).toHaveAttribute("data-label", "Your Branch");
  });

  it("shows period deltas in the accessible summary", () => {
    render(<TrendChart history={history} title="Where is it heading?" mainKey="own:mine" />);

    expect(screen.getByText(/Your Branch added 8 reviews/i)).toBeInTheDocument();
    expect(screen.getByText(/Your Branch rating changed by \+0.30/i)).toBeInTheDocument();
  });

  it("renders an explicit insufficient-history state", () => {
    render(
      <TrendChart
        history={[{ key: "own:mine", kind: "own", name: "Your Branch", points: [history[0].points[0]] }]}
        title="Where is it heading?"
        mainKey="own:mine"
      />,
    );

    expect(screen.getByText(/Not enough history yet/i)).toBeInTheDocument();
  });
});
