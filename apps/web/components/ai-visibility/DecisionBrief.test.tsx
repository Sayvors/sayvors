import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DecisionBrief from "./DecisionBrief";
import ClaimLedger from "./ClaimLedger";

const detail = {
  answer_text: "Acme Coffee is recommended [S2].",
  mentioned: true,
  cited: true,
  recommended: true,
  incorrect: false,
  competitor_mentions: [],
  evidence_coverage: { source_count: 2, validated_claim_count: 1 },
  claims: [
    {
      claim: "Acme is recommended",
      quote: "Acme is recommended",
      source_ids: ["S2"],
      status: "supported" as const,
    },
  ],
  actions: [
    {
      priority: "P0" as const,
      category: "fact_correction",
      title: "Correct phone",
      rationale: "Source contradicts the listing.",
      deep_link: "/dashboard/locations?tab=details",
      effort: "low" as const,
      evidence: { source_ids: ["S1"] },
    },
  ],
  sources: [
    {
      id: "source-failed",
      label: "S1",
      position: 0,
      url: "https://failed.example",
      title: "Failed source",
      snippet: null,
      excerpt: null,
      fetch_error: "unsupported_content_type",
    },
    {
      id: "src-1",
      label: "S2",
      position: 1,
      url: "https://example.com",
      title: "Example",
      snippet: null,
      excerpt: "Acme is recommended",
      fetch_error: null,
    },
  ],
};

const copy = {
  disclosure: "Grounded AI",
  answer: "Grounded answer",
  claimLedger: "Claim ledger",
  supported: "Supported",
  contradicted: "Contradicted",
  unsupported: "Unsupported",
  competitors: "Competitor evidence",
  fixNext: "Fix next",
  sources: "Sources",
  evidence: "Evidence",
  noActions: "No actions",
  readFullAnswer: "Read full answer",
  fullAnswer: "Full grounded answer",
  close: "Close",
  mentioned: "Mentioned",
  cited: "Cited",
  recommended: "Recommended",
  incorrect: "Incorrect",
};

describe("DecisionBrief", () => {
  it("renders cited answer and evidence-backed actions", () => {
    render(<DecisionBrief detail={detail as never} copy={copy as never} />);
    expect(screen.getByText(/Acme Coffee is recommended/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "[S2]" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
    expect(screen.getByText("Correct phone")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Correct phone" })).toHaveAttribute(
      "href",
      "/dashboard/locations?tab=details",
    );
  });
  it("opens long answers in an accessible dialog", () => {
    const tail = "Unique grounded evidence at the end of a long answer";
    const longAnswer = `${detail.answer_text} ${"Additional sourced evidence [S2]. ".repeat(40)}${tail} [S2].`;
    render(
      <DecisionBrief
        detail={{ ...detail, answer_text: longAnswer } as never}
        copy={copy as never}
      />,
    );
    expect(screen.queryByText(tail, { exact: false })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Read full answer" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Full grounded answer" });
    expect(dialog.textContent).toContain(tail);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});

describe("ClaimLedger", () => {
  it("shows claim status and exact quote", () => {
    render(
      <ClaimLedger
        claims={detail.claims}
        sources={detail.sources}
        copy={copy as never}
      />,
    );
    expect(screen.getByText("Supported")).toBeInTheDocument();
    expect(screen.getAllByText("Acme is recommended")).toHaveLength(2);
  });
});
