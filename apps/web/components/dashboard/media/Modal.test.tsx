import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import Modal from "./Modal";

function NestedModals() {
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
      >
        <button type="button" onClick={() => setInnerOpen(true)}>
          Open inner
        </button>
        <Modal
          open={innerOpen}
          onClose={() => setInnerOpen(false)}
          title="Inner dialog"
        >
          <button type="button">Inner action</button>
        </Modal>
      </Modal>
    </>
  );
}

describe("Modal", () => {
  it("gives nested dialogs unique names and closes only the topmost on Escape", () => {
    render(<NestedModals />);
    const outerTrigger = screen.getByRole("button", { name: "Open outer" });
    outerTrigger.focus();
    fireEvent.click(outerTrigger);
    const outer = screen.getByRole("dialog", { name: "Outer dialog" });
    const innerTrigger = within(outer).getByRole("button", { name: "Open inner" });
    innerTrigger.focus();
    fireEvent.click(innerTrigger);

    expect(screen.getByRole("dialog", { name: "Inner dialog" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Inner dialog" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Outer dialog" })).toBeInTheDocument();
    expect(innerTrigger).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Outer dialog" })).not.toBeInTheDocument();
    expect(outerTrigger).toHaveFocus();
  });
});
