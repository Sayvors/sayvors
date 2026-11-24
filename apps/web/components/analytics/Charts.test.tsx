import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MetricChart, RatingDistribution, SentimentSplitBar } from "./Charts";

const point = (date: string, reviews_count: number, positive_count: number, neutral_count: number, negative_count: number, impressions_maps: number) => ({
  date,
  channel_id: "channel-1",
  reviews_count,
  avg_rating: 4.4,
  positive_count,
  neutral_count,
  negative_count,
  replies_count: reviews_count,
  impressions_maps,
  website_clicks: 0,
  call_clicks: 0,
  direction_requests: 0,
});

const points = [
  point("2026-11-01", 4, 3, 1, 0, 20),
  point("2026-11-02", 7, 5, 1, 1, 35),
];

describe("RatingDistribution", () => {
  it("renders a colored star donut with the average in the center", () => {
    const { container } = render(
      <RatingDistribution
        distribution={{ "5": 8, "4": 4, "3": 2, "2": 1, "1": 1 }}
        total={16}
        averageRating={4.4}
      />,
    );

    expect(screen.getByText("4.4")).toBeInTheDocument();
    expect(screen.getByText("5★")).toBeInTheDocument();
    expect(screen.getByText("1★")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-star-segment]")).toHaveLength(5);
  });

  it("shows an explicit empty state when there are no ratings", () => {
    render(<RatingDistribution distribution={{}} total={0} averageRating={null} />);

    expect(screen.getByText("No ratings yet")).toBeInTheDocument();
  });
});

describe("SentimentSplitBar", () => {
  it("renders a donut with the positive share in the center", () => {
    render(<SentimentSplitBar positive={82} neutral={10} negative={8} />);

    expect(screen.getByRole("img", { name: /Sentiment mix/i })).toBeInTheDocument();
    expect(screen.getAllByText("82%")).toHaveLength(2);
    expect(screen.getByText("Negative")).toBeInTheDocument();
  });
});

describe("MetricChart", () => {
  it("aggregates channels that share a date instead of drawing duplicate bars", () => {
    const { container } = render(<MetricChart points={[...points, point("2026-11-01", 2, 1, 1, 0, 5)]} />);

    expect(container.querySelectorAll("[data-metric-bar]")).toHaveLength(2);
    expect(container.querySelector("[data-metric-bar] title")?.textContent).toContain("6");
  });

  it("renders review volume as colored bars", () => {
    const { container } = render(<MetricChart points={points} />);

    expect(container.querySelectorAll("[data-metric-bar]")).toHaveLength(2);
    expect(container.querySelector("[data-metric-bar]")).toHaveAttribute("fill", "#3D1D6E");
  });

  it("renders sentiment over time as stacked positive/neutral/negative bars", async () => {
    const user = userEvent.setup();
    const { container } = render(<MetricChart points={points} />);

    await user.click(screen.getByRole("button", { name: "Sentiment" }));

    expect(container.querySelectorAll('[data-stack="positive"]')).toHaveLength(2);
    expect(container.querySelectorAll('[data-stack="neutral"]')).toHaveLength(2);
    expect(container.querySelectorAll('[data-stack="negative"]')).toHaveLength(2);
    expect(container.querySelector('[data-stack="positive"]')).toHaveAttribute("fill", "#116631");
  });
});
