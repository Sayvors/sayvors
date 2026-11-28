import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResearchProgress from "./ResearchProgress";

const copy = {
  scanning: "Scanning public pages",
  checking: "Checking claims",
  ready: "Brief ready",
  stopped: "Research stopped",
  progress: "Research progress",
};

describe("ResearchProgress", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps per-second elapsed updates out of live announcements", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-28T10:00:00Z"));
    render(
      <ResearchProgress
        status="fetching"
        createdAt="2026-11-28T10:00:00Z"
        copy={copy as never}
      />,
    );

    expect(screen.getByText("0s")).toHaveAttribute("aria-hidden", "true");
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("1s")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Scanning public pages");
  });

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
