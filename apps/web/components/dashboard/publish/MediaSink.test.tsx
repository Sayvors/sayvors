import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MediaSink from "./MediaSink";

// Media library loading is network; keep the tab tests deterministic.
vi.mock("@/lib/api-rag", () => ({
  apiFetch: vi.fn(async () => ({ media: [] })),
}));

const noop = () => {};
const baseProps = {
  media: null,
  onPick: noop,
  onClear: noop,
};

describe("MediaSink image picker", () => {
  it("shows the three standard sources as tabs, Upload active by default", () => {
    render(<MediaSink {...baseProps} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Upload", "From a link", "Your library"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
  });

  it("shows only the active panel's content", () => {
    render(<MediaSink {...baseProps} />);
    // Upload panel: drop title + browse. Link panel not mounted.
    expect(screen.getByText(/drop an image or video here/i)).toBeInTheDocument();
    expect(screen.queryByText(/paste a public https link/i)).toBeNull();
  });

  it("switches to the link panel and back", async () => {
    const user = userEvent.setup();
    render(<MediaSink {...baseProps} />);
    await user.click(screen.getByRole("tab", { name: /from a link/i }));
    expect(screen.getByRole("tab", { name: /from a link/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/paste a public https link/i)).toBeInTheDocument();
    expect(screen.queryByText(/drop an image or video here/i)).toBeNull();

    await user.click(screen.getByRole("tab", { name: /upload/i }));
    expect(screen.getByText(/drop an image or video here/i)).toBeInTheDocument();
  });

  it("renders the chosen-media card with replace and remove actions", () => {
    render(
      <MediaSink
        {...baseProps}
        media={{ type: "image", url: "https://example.com/x.jpg", fileName: "x.jpg", sizeBytes: 2048 }}
      />,
    );
    expect(screen.getByText("x.jpg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /replace/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove media/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();
  });
});
