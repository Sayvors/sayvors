import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PromptLibrary from "./PromptLibrary";

const copy = {
  promptLibrary: "Prompt library",
  searchPrompts: "Search prompts",
  addPrompt: "Add prompt",
  editPrompt: "Edit prompt",
  archivePrompt: "Archive",
  deletePrompt: "Delete",
  titleLabel: "Title",
  promptLabel: "Research question",
  intentLabel: "Intent",
  savePrompt: "Save prompt",
  cancel: "Cancel",
  noPrompts: "No prompts yet.",
  suggestionsTitle: "Suggested questions",
  useSuggestion: "Use",
  active: "Active",
  archived: "Archived",
};

describe("PromptLibrary", () => {
  it("shows the empty state and suggestions", () => {
    render(
      <PromptLibrary
        channelId="branch-1"
        copy={copy as never}
        prompts={[]}
        suggestions={["Best coffee near Malqa"]}
        selectedId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText("No prompts yet.")).toBeInTheDocument();
    expect(screen.getByText("Best coffee near Malqa")).toBeInTheDocument();
  });

  it("keeps the form after a failed create", async () => {
    const onCreate = vi.fn().mockRejectedValue(new Error("blocked"));
    render(
      <PromptLibrary
        channelId="branch-1"
        copy={copy as never}
        prompts={[]}
        suggestions={[]}
        selectedId={null}
        onSelect={vi.fn()}
        onCreate={onCreate}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add prompt" }));
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Coffee" },
    });
    fireEvent.change(screen.getByLabelText("Research question"), {
      target: { value: "Best coffee near Malqa" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save prompt" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("blocked");
    expect(screen.getByLabelText("Title")).toHaveValue("Coffee");
  });
});
