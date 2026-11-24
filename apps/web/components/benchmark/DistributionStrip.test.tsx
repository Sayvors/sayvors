import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DistributionStrip from "./DistributionStrip";
import type { ComparisonSubject } from "@/lib/api-benchmark";

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
      total_reviews: 10,
      reviews_last_day: 0,
      reviews_last_week: 1,
      reviews_last_month: 2,
      reviews_last_year: 24,
      avg_rating: 4.6,
      total_ratings: 10,
      five_star: 7,
      four_star: 2,
      one_star: 1,
      impressions: null,
      calls: null,
      period_reviews: 2,
      period_avg_rating: 4.6,
      rating_change: 0,
      period_impressions: null,
      period_calls: null,
    },
    facts: {
      positive_pct: 70,
      negative_pct: 10,
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

const own = subject("own:main", "Your Branch", {
  metrics: {
    ...subject("own:x", "x").metrics,
    avg_rating: 4.8,
    reviews_last_month: 3,
    total_reviews: 30,
  },
  facts: { ...subject("own:x", "x").facts, positive_pct: 80 },
});
const peer = subject("own:peer", "Peer Branch", {
  metrics: {
    ...subject("own:x", "x").metrics,
    avg_rating: 4.4,
    reviews_last_month: 1,
    total_reviews: 12,
  },
  facts: { ...subject("own:x", "x").facts, positive_pct: 60 },
});
const noRating = subject("own:new", "New Branch", {
  metrics: {
    ...subject("own:x", "x").metrics,
    avg_rating: 0,
    total_ratings: 0,
    five_star: 0,
    four_star: 0,
    one_star: 0,
    total_reviews: 0,
    reviews_last_month: 0,
  },
  facts: { ...subject("own:x", "x").facts, positive_pct: 0, negative_pct: 0 },
});

describe("DistributionStrip", () => {
  it("renders the four owner metrics and pins the selected branch", () => {
    render(
      <DistributionStrip
        subjects={[own, peer, noRating]}
        mainKey={own.key}
      />,
    );

    expect(screen.getByRole("heading", { name: "Where you stand" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Your Branch: 4.8" })).toBeInTheDocument();
    expect(screen.getAllByText("4.8").length).toBeGreaterThan(0);
    expect(screen.getAllByText("80%").length).toBeGreaterThan(0);
  });

  it("excludes a no-rating branch from rating and sentiment sample counts", () => {
    render(
      <DistributionStrip
        subjects={[own, peer, noRating]}
        mainKey={own.key}
      />,
    );

    expect(
      screen.getByText(/Rating: 2 of 3 businesses have ratings/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Positive share: 2 of 3 businesses have review text/i),
    ).toBeInTheDocument();
  });

  it("keeps zero total reviews as a real value", () => {
    render(
      <DistributionStrip
        subjects={[own, peer, noRating]}
        mainKey={own.key}
      />,
    );

    expect(
      screen.getByText(/Total reviews: 3 of 3 businesses report review counts/i),
    ).toBeInTheDocument();
  });

  it("labels small comparison sets instead of overstating the gap", () => {
    render(
      <DistributionStrip
        subjects={[own, peer]}
        mainKey={own.key}
      />,
    );

    expect(screen.getAllByText(/Small comparison set/i).length).toBeGreaterThan(0);
  });

  it("says tied when the selected branch equals the median", () => {
    const tiedPeer = subject("own:tied", "Tied Peer", {
      metrics: { ...peer.metrics, avg_rating: 4.8 },
    });
    render(
      <DistributionStrip
        subjects={[own, tiedPeer]}
        mainKey={own.key}
      />,
    );

    expect(screen.getAllByText("At median").length).toBeGreaterThan(0);
  });

  it("renders an explicit empty state when no subjects are available", () => {
    render(<DistributionStrip subjects={[]} mainKey={null} />);

    expect(screen.getByText(/Add at least two businesses/i)).toBeInTheDocument();
  });
});
