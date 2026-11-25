import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DecisionBrief from "./DecisionBrief";
import ClaimLedger from "./ClaimLedger";

const detail = {
  answer_text: "Acme Coffee is recommended [S1].",
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
      source_ids: ["S1"],
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
      id: "src-1",
      position: 0,
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
  mentioned: "Mentioned",
  cited: "Cited",
  recommended: "Recommended",
  incorrect: "Incorrect",
};

describe("DecisionBrief", () => {
  it("renders cited answer and evidence-backed actions", () => {
    render(<DecisionBrief detail={detail as never} copy={copy as never} />);
    expect(screen.getByText(/Acme Coffee is recommended/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "S1" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
    expect(screen.getByText("Correct phone")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Correct phone" })).toHaveAttribute(
      "href",
      "/dashboard/locations?tab=details",
    );
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
