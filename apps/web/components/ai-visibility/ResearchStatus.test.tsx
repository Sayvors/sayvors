import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/en";
import ResearchStatus from "./ResearchStatus";

describe("ResearchStatus", () => {
  it("shows non-blocking progress while research runs", () => {
    render(
      <ResearchStatus
        status="running"
        phase="researching"
        version={2}
        completed={3}
        total={8}
        error={null}
        copy={en.aiVisibility}
      />,
    );
    expect(screen.getByText("Research in progress")).toBeInTheDocument();
    expect(screen.getByText(/come back later/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "38");
  });

  it("renders nothing after completion", () => {
    const { container } = render(
      <ResearchStatus status="completed" phase="complete" version={1} completed={8} total={8} error={null} copy={en.aiVisibility} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
