import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GoogleCoverSection from "./GoogleCoverSection";

const monitor = (status: string) => ({
  id: "m-1",
  channel_id: "google:9",
  status,
  image_url: "https://lh3.googleusercontent.com/real-cover",
  expected_image_url: "https://example.com/mine.jpg",
  actual_image_url: "https://lh3.googleusercontent.com/real-cover",
  message: "Google replaced your cover photo. Replace it again.",
  drift_count: 1,
  last_checked_at: "2026-11-23T10:00:00Z",
});

vi.mock("@/lib/api-rag", () => ({
  apiFetch: vi.fn(async () => [monitor("changed")]),
}));

describe("Google Cover section", () => {
  it("shows the real Google image and a changed warning", async () => {
    render(<GoogleCoverSection locale="en" onReplace={() => {}} />);

    expect(await screen.findByText(/google changed your cover photo/i)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /google cover photo/i })).toHaveAttribute(
      "src",
      "https://lh3.googleusercontent.com/real-cover",
    );
  });

  it("sends the channel id when Replace again is clicked", async () => {
    const onReplace = vi.fn();
    const user = userEvent.setup();
    render(<GoogleCoverSection locale="en" onReplace={onReplace} />);

    await user.click(await screen.findByRole("button", { name: /replace again/i }));

    expect(onReplace).toHaveBeenCalledWith("google:9");
  });
});
