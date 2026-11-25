import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ReviewResponseTable from "./ReviewResponseTable";
import type { SubjectReviews } from "@/lib/api-benchmark";

const subjects: SubjectReviews[] = [
  {
    key: "own:mine",
    name: "My Branch",
    summary: { total: 3, sampled: 3, answered: 1, unanswered: 2, response_rate: 33.3 },
    reviews: [],
  },
  {
    key: "saved:peer",
    name: "Competitor",
    summary: { total: 70, sampled: 0, answered: 0, unanswered: 0, response_rate: null },
    reviews: [],
  },
];

describe("ReviewResponseTable", () => {
  it("shows total, answered, unanswered and response rate per business", () => {
    render(<ReviewResponseTable subjects={subjects} loading={false} />);

    expect(screen.getByRole("table", { name: "Review responses" })).toBeInTheDocument();
    expect(screen.getByText("70")).toBeInTheDocument();
    expect(screen.getByText("33.3%").closest("td")).toHaveAttribute("data-tone", "weak");
    expect(screen.getByText("Answered")).toBeInTheDocument();
    expect(screen.getByText("Not answered")).toBeInTheDocument();
  });

  it("does not invent response counts when no review sample exists", () => {
    render(<ReviewResponseTable subjects={subjects} loading={false} />);

    expect(screen.getAllByText("No recent sample").length).toBeGreaterThan(0);
  });

  it("shows a retryable error instead of an empty table", () => {
    const onRetry = vi.fn();
    render(
      <ReviewResponseTable
        subjects={[]}
        loading={false}
        error={new Error("reviews unavailable")}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load review responses.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
