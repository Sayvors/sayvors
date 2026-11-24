import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import OwnScorecards from "./OwnScorecards";
import type { ComparisonSubject, HistoryPoint } from "@/lib/api-benchmark";

function subject(
  key: string,
  name: string,
  over: Partial<ComparisonSubject> = {},
): ComparisonSubject {
  return {
    key,
    kind: "own",
    id: key.replace("own:", ""),
    available: true,
    reason: null,
    name,
    address: null,
    verified: true,
    data_source: "sayvors_analytics",
    metrics: {
      total_reviews: 30,
      reviews_last_day: 0,
      reviews_last_week: 2,
      reviews_last_month: 3,
      reviews_last_year: 36,
      avg_rating: 4.8,
      total_ratings: 30,
      five_star: 26,
      four_star: 2,
      one_star: 2,
      impressions: null,
      calls: null,
      period_reviews: 3,
      period_avg_rating: 4.8,
      rating_change: 0,
      period_impressions: null,
      period_calls: null,
    },
    facts: {
      positive_pct: 80,
      negative_pct: 7,
      branch: name,
      employee_mentions: 0,
      working_hard_mentions: 0,
      menu_price_mentions: 0,
      parking_praised: 0,
      parking_criticised: 0,
      services: [],
      top_problems: [],
      named_team: [],
    },
    notes: [],
    tags: [],
    ...over,
  };
}

const main = subject("own:main", "Main Branch");
const peer = subject("own:peer", "Peer Branch", {
  metrics: {
    ...subject("own:x", "x").metrics,
    avg_rating: 4.4,
    total_reviews: 12,
    total_ratings: 12,
    five_star: 8,
    reviews_last_month: 1,
  },
});
const fresh = subject("own:fresh", "Fresh Branch", {
  metrics: {
    ...subject("own:x", "x").metrics,
    avg_rating: 0,
    total_reviews: 0,
    total_ratings: 0,
    five_star: 0,
    four_star: 0,
    one_star: 0,
    reviews_last_month: 0,
    reviews_last_year: 0,
  },
  facts: { ...subject("own:x", "x").facts, positive_pct: 0, negative_pct: 0 },
});
const small = subject("own:small", "Small Sample", {
  metrics: {
    ...subject("own:x", "x").metrics,
    avg_rating: 3.8,
    total_reviews: 3,
    total_ratings: 3,
    five_star: 1,
    reviews_last_month: 0,
  },
});

const history: Record<string, HistoryPoint[]> = {
  "own:main": [
    { at: "2026-10-01T00:00:00Z", rating: 4.6, reviews: 20 },
    { at: "2026-11-01T00:00:00Z", rating: 4.8, reviews: 30 },
  ],
};

describe("OwnScorecards", () => {
  it("does not flag a no-rating branch as below median", () => {
    render(<OwnScorecards subjects={[main, fresh]} mainKey={main.key} />);

    expect(screen.getByText("No rating yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request your first reviews" })).toHaveAttribute(
      "href",
      "/dashboard/reviews",
    );
    expect(screen.queryByText(/off your median/i)).not.toBeInTheDocument();
  });

  it("labels low samples instead of issuing a confident variance warning", () => {
    render(<OwnScorecards subjects={[main, small]} mainKey={main.key} />);

    expect(screen.getAllByText("Small sample").length).toBeGreaterThan(0);
    expect(screen.queryByText(/off your median/i)).not.toBeInTheDocument();
  });

  it("shows the selected branch and its gap to the own median", () => {
    render(<OwnScorecards subjects={[main, peer]} mainKey={main.key} />);

    expect(screen.getByText("Selected")).toBeInTheDocument();
    expect(screen.getByText(/above branch median/i)).toBeInTheDocument();
  });

  it("turns the top problem into a concrete review action", () => {
    const problem = subject("own:problem", "Problem Branch", {
      facts: { ...subject("own:x", "x").facts, top_problems: ["Slow service"] },
    });
    render(<OwnScorecards subjects={[problem]} mainKey={problem.key} />);

    expect(screen.getByText("Top problem: Slow service")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review low-star feedback" })).toBeInTheDocument();
  });

  it("renders an accessible sparkline when history exists", () => {
    render(
      <OwnScorecards
        subjects={[main]}
        mainKey={main.key}
        historyBySubject={history}
      />,
    );

    expect(screen.getByRole("img", { name: "Rating trend for Main Branch" })).toBeInTheDocument();
  });

  it("renders an actionable empty state", () => {
    render(<OwnScorecards subjects={[]} mainKey={null} />);

    expect(screen.getByText(/Connect a Google location/i)).toBeInTheDocument();
  });
});
