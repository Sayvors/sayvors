import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import NorthStarCard from "./NorthStarCard";
import type { CompareSummary } from "@/lib/api-benchmark";

const summary: CompareSummary = {
  rank: 1,
  of: 2,
  own: { key: "own:mine", name: "My Branch" },
  leader: { key: "own:mine", name: "My Branch" },
  gaps: { avg_rating: 0, reviews_per_month: 0, positive_pct: 0 },
  health: "bad",
};

describe("NorthStarCard", () => {
  it("does not call the ranked leader at risk", () => {
    render(<NorthStarCard summary={summary} />);

    expect(screen.getByText("Leading")).toBeInTheDocument();
    expect(screen.queryByText("At risk")).not.toBeInTheDocument();
  });
});
