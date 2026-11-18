import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import IntakeChoiceGrid from "./IntakeChoiceGrid";
import type { IntakeChoice } from "@/lib/business-intake";

const choices: IntakeChoice[] = [
  { key: "halal", title: "Halal", description: "Tap to select" },
  { key: "google", title: "Vegan", description: "Use what Google already knows", badge: "From Google" },
  { key: "skip", title: "Not sure", description: "Leave this one blank", tone: "notSure" },
];

describe("intake choice grid", () => {
  it("renders every option as a tappable card with its description", () => {
    render(
      <IntakeChoiceGrid
        label="Dietary options"
        choices={choices}
        selected={[]}
        multiple
        onChoose={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByText("Tap to select")).toBeInTheDocument();
    expect(screen.getByText("From Google")).toBeInTheDocument();
  });

  it("marks a selected card and reports the choice", async () => {
    const onChoose = vi.fn();
    const user = userEvent.setup();
    render(
      <IntakeChoiceGrid
        label="Dietary options"
        choices={choices}
        selected={["halal"]}
        multiple
        onChoose={onChoose}
      />,
    );
    const halal = screen.getByRole("button", { name: /halal/i });
    expect(halal).toHaveAttribute("aria-pressed", "true");
    expect(halal.className).toContain("bg-deep-violet");
    await user.click(screen.getByRole("button", { name: /vegan/i }));
    expect(onChoose).toHaveBeenCalledWith("google");
  });

  it("uses radio semantics for single-select and a distinct style for 'Not sure'", () => {
    render(
      <IntakeChoiceGrid
        label="Reservations"
        choices={choices}
        selected={["skip"]}
        onChoose={vi.fn()}
      />,
    );
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
    const skip = screen.getByRole("radio", { name: /not sure/i });
    expect(skip).toHaveAttribute("aria-checked", "true");
    expect(skip.className).toContain("bg-amber-300");
  });
});
