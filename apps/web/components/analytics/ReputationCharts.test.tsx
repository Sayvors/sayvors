import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DonutChart, ImportOutcomesDonut, RatingTrend, ReviewVolumeBars } from "./ReputationCharts";

describe("DonutChart", () => {
  it("renders the center value, legend, and an accessible summary", () => {
    render(
      <DonutChart
        ariaLabel="Sentiment mix"
        centerValue="82%"
        centerLabel="Positive"
        segments={[
          { label: "Positive", value: 82, color: "#116631" },
          { label: "Neutral", value: 10, color: "#8A6100" },
          { label: "Negative", value: 8, color: "#B3123A" },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: /Sentiment mix/i })).toBeInTheDocument();
    expect(screen.getAllByText("Positive")).toHaveLength(2);
    expect(screen.getAllByText("82%")).toHaveLength(2);
    expect(screen.getByText("8%")).toBeInTheDocument();
  });

  it("shows an explicit empty state instead of a misleading full ring", () => {
    render(
      <DonutChart
        ariaLabel="Import outcomes"
        centerValue="0"
        centerLabel="Total"
        emptyLabel="No outcomes yet"
        segments={[{ label: "Published", value: 0, color: "#3D1D6E" }]}
      />,
    );

    expect(screen.getByText("No outcomes yet")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Import outcomes/i })).not.toBeInTheDocument();
  });

  it("clamps negative values out of the geometry", () => {
    const { container } = render(
      <DonutChart
        ariaLabel="Outcomes"
        centerValue="3"
        centerLabel="Total"
        segments={[
          { label: "Good", value: 3, color: "#116631" },
          { label: "Bad", value: -5, color: "#B3123A" },
        ]}
      />,
    );

    const segments = container.querySelectorAll("[data-donut-segment]");
    expect(segments).toHaveLength(1);
  });
});

describe("ImportOutcomesDonut", () => {
  const labels = {
    unanswered: "Unanswered before",
    published: "Published now",
    alreadyAnswered: "Already answered",
    needsAttention: "Needs attention",
  };

  it("shows the import outcome mix with the total in the center", () => {
    render(
      <ImportOutcomesDonut
        labels={labels}
        counts={{ unanswered: 2, published: 8, alreadyAnswered: 6, needsAttention: 1 }}
      />,
    );

    expect(screen.getByText("17")).toBeInTheDocument();
    expect(screen.getByText("Published now")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Import outcomes/i })).toBeInTheDocument();
  });

  it("shows an empty state when the import produced no outcomes", () => {
    render(
      <ImportOutcomesDonut
        labels={labels}
        counts={{ unanswered: 0, published: 0, alreadyAnswered: 0, needsAttention: 0 }}
      />,
    );

    expect(screen.getByText("No import outcomes yet")).toBeInTheDocument();
  });
});

describe("ReviewVolumeBars", () => {
  it("renders each month and highlights the latest bar", () => {
    render(
      <ReviewVolumeBars
        ariaLabel="Reviews received"
        emptyLabel="No review volume yet"
        data={[
          { label: "2026-09", value: 4 },
          { label: "2026-10", value: 9 },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: /Reviews received/i })).toBeInTheDocument();
    expect(screen.getByTitle("2026-09: 4")).toBeInTheDocument();
    expect(screen.getByTitle("2026-10: 9")).toHaveAttribute("data-highlight", "true");
  });

  it("shows an empty state when there are no months", () => {
    render(
      <ReviewVolumeBars
        ariaLabel="Reviews received"
        emptyLabel="No review volume yet"
        data={[]}
      />,
    );

    expect(screen.getByText("No review volume yet")).toBeInTheDocument();
  });
});

describe("RatingTrend", () => {
  it("colors points by star rating and draws an average line", () => {
    const { container } = render(
      <RatingTrend
        ariaLabel="Rating over time"
        emptyLabel="No rating history yet"
        data={[
          { date: "2026-10-01", rating: 5 },
          { date: "2026-10-02", rating: 2 },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: /Rating over time/i })).toBeInTheDocument();
    const points = container.querySelectorAll("[data-rating-point]");
    expect(points).toHaveLength(2);
    expect(points[0]).toHaveAttribute("fill", "#116631");
    expect(points[1]).toHaveAttribute("fill", "#C2410C");
    expect(container.querySelector("[data-average-line]")).toBeInTheDocument();
  });

  it("shows an empty state when there is no history", () => {
    render(
      <RatingTrend
        ariaLabel="Rating over time"
        emptyLabel="No rating history yet"
        data={[]}
      />,
    );

    expect(screen.getByText("No rating history yet")).toBeInTheDocument();
  });
});
