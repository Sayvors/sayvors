import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import SentimentVelocityBars from "./SentimentVelocityBars";
import type { ComparisonSubject } from "@/lib/api-benchmark";

function subject(
  key: string,
  name: string,
  kind: "own" | "saved",
  over: Partial<ComparisonSubject> = {},
): ComparisonSubject {
  return {
    key,
    kind,
    id: key.split(":")[1],
    available: true,
    reason: null,
    name,
    address: null,
    verified: false,
    data_source: kind === "own" ? "sayvors_analytics" : "google_places",
    metrics: {
      total_reviews: 24,
      reviews_last_day: 0,
      reviews_last_week: 2,
      reviews_last_month: 8,
      reviews_last_year: 96,
      avg_rating: 4.6,
      total_ratings: 24,
      five_star: 18,
      four_star: 4,
      one_star: 2,
      star_share_base: 24,
      impressions: null,
      calls: null,
      period_reviews: 8,
      period_avg_rating: 4.6,
      rating_change: 0,
      period_impressions: null,
      period_calls: null,
    },
    facts: {
      positive_pct: 75,
      negative_pct: 8,
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

const own = subject("own:mine", "Your Branch", "own");
const saved = subject("saved:peer", "Competitor", "saved", {
  metrics: {
    ...subject("saved:x", "x", "saved").metrics,
    reviews_last_month: 3,
  },
  facts: { ...subject("saved:x", "x", "saved").facts, positive_pct: 82, negative_pct: 4 },
});
const empty = subject("own:new", "New Branch", "own", {
  metrics: {
    ...subject("own:x", "x", "own").metrics,
    total_reviews: 0,
    total_ratings: 0,
    reviews_last_month: 0,
    reviews_last_year: 0,
    avg_rating: 0,
  },
  facts: { ...subject("own:x", "x", "own").facts, positive_pct: 0, negative_pct: 0 },
});

describe("SentimentVelocityBars", () => {
  it("separates reputation mix from review momentum", () => {
    render(<SentimentVelocityBars subjects={[own, saved]} mainKey={own.key} />);

    expect(screen.getByRole("heading", { name: "Reputation mix" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New reviews per month" })).toBeInTheDocument();
  });

  it("labels the sentiment source instead of comparing unlike methods as equals", () => {
    render(<SentimentVelocityBars subjects={[own, saved]} mainKey={own.key} />);

    expect(screen.getByText("Classified from review text")).toBeInTheDocument();
    expect(screen.getByText("From star ratings")).toBeInTheDocument();
  });

  it("does not render a no-review branch in the reputation mix", () => {
    render(<SentimentVelocityBars subjects={[own, empty]} mainKey={own.key} />);

    const panel = screen.getByRole("heading", { name: "Reputation mix" }).parentElement!;
    expect(within(panel).queryByText("New Branch")).not.toBeInTheDocument();
    expect(within(panel).queryByText(/0% positive/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("Small sample").length).toBeGreaterThan(0);
  });

  it("keeps a real zero-review velocity visible", () => {
    render(<SentimentVelocityBars subjects={[empty]} mainKey={empty.key} />);

    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("renders an actionable empty state", () => {
    render(<SentimentVelocityBars subjects={[]} mainKey={null} />);

    expect(screen.getByText(/Save a competitor or connect a Google location/i)).toBeInTheDocument();
  });
});
