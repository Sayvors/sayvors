import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import Modal from "./Modal";

function NestedModals({ busy = false }: { busy?: boolean }) {
  const [outerOpen, setOuterOpen] = useState(false);
  const [innerOpen, setInnerOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOuterOpen(true)}>
        Open outer
      </button>
      <Modal
        open={outerOpen}
        onClose={() => {
          setInnerOpen(false);
          setOuterOpen(false);
        }}
        title="Outer dialog"
        busy={busy}
      >
        <button type="button" onClick={() => setInnerOpen(true)}>
          Open inner
        </button>
        <Modal
          open={innerOpen}
          onClose={() => setInnerOpen(false)}
          title="Inner dialog"
          busy={busy}
        >
          <button type="button">Inner action</button>
        </Modal>
      </Modal>
    </>
  );
}

describe("Modal", () => {
  it("includes native evidence summaries in keyboard focus order", async () => {
    const user = userEvent.setup();
    render(
      <Modal open onClose={vi.fn()} title="Decision brief">
        <details open>
          <summary>Evidence</summary>
          <button type="button">Evidence action</button>
        </details>
      </Modal>,
    );
    const close = screen.getByRole("button", { name: "Close" });
    const summary = screen.getByText("Evidence");
    expect(close).toHaveFocus();

    await user.tab();
    expect(summary).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
  });

  it("keeps nested focus and scroll locks scoped to the topmost dialog", () => {
    const initialOverflow = document.body.style.overflow;
    const { rerender } = render(<NestedModals />);
    const outerTrigger = screen.getByRole("button", { name: "Open outer" });
    outerTrigger.focus();
    fireEvent.click(outerTrigger);
    expect(document.body.style.overflow).toBe("hidden");
    const outer = screen.getByRole("dialog", { name: "Outer dialog" });
    const innerTrigger = within(outer).getByRole("button", { name: "Open inner" });
    innerTrigger.focus();
    fireEvent.click(innerTrigger);

    const inner = screen.getByRole("dialog", { name: "Inner dialog" });
    const innerClose = within(inner).getByRole("button", { name: "Close" });
    const innerAction = within(inner).getByRole("button", { name: "Inner action" });
    expect(innerClose).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(innerAction).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(innerClose).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    rerender(<NestedModals busy />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Inner dialog" })).toBeInTheDocument();
    rerender(<NestedModals busy={false} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Inner dialog" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Outer dialog" })).toBeInTheDocument();
    expect(innerTrigger).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Outer dialog" })).not.toBeInTheDocument();
    expect(outerTrigger).toHaveFocus();
    expect(document.body.style.overflow).toBe(initialOverflow);
  });
});
