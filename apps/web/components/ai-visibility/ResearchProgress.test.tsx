import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ResearchProgress from "./ResearchProgress";

const copy = {
  scanning: "Scanning public pages",
  checking: "Checking claims",
  ready: "Brief ready",
  stopped: "Research stopped",
  progress: "Research progress",
};

describe("ResearchProgress", () => {
  it("maps active stages to human steps and a determinate progress element", () => {
    render(<ResearchProgress status="fetching" completed={1} total={4} elapsedSeconds={12} copy={copy as never} />);
    expect(screen.getByText("Scanning public pages")).toBeInTheDocument();
    expect(screen.queryByText("fetching")).not.toBeInTheDocument();
    const progress = screen.getByRole("progressbar", { name: "Research progress" });
    expect(progress).toHaveAttribute("aria-valuenow", "25");
    expect(progress).toHaveAttribute("max", "100");
    expect(screen.getByText("12s")).toBeInTheDocument();
  });
});
