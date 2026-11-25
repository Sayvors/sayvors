import { describe, expect, it } from "vitest";

import { getMetricRows } from "./benchmark-rows";

const copy = {
  reviewsTotal: "Total reviews",
  averageRating: "Average rating",
  reviewsLastMonth: "Reviews · last 30 days",
  reviewsLastYear: "Reviews · last 12 months",
  fiveStarRatings: "5-star reviews (%)",
  oneStarRatings: "1-star reviews (%)",
};

describe("benchmark metric scope", () => {
  it("keeps the primary comparison at exactly six reputation metrics", () => {
    expect(getMetricRows(copy).map((row) => row.key)).toEqual([
      "total_reviews",
      "avg_rating",
      "reviews_last_month",
      "reviews_last_year",
      "five_star_pct",
      "one_star_pct",
    ]);
  });

  it("attaches an explicit unit to every comparable metric", () => {
    const rows = getMetricRows(copy);
    expect(rows.find((row) => row.key === "total_reviews")?.gapUnit).toBe("count");
    expect(rows.find((row) => row.key === "avg_rating")?.gapUnit).toBe("rating");
    expect(rows.find((row) => row.key === "five_star_pct")?.gapUnit).toBe("percent");
    expect(rows.find((row) => row.key === "one_star_pct")?.gapUnit).toBe("percent");
  });
});
