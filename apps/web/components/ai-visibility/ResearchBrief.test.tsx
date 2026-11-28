import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResearchBrief from "./ResearchBrief";

vi.mock("./ResearchProvenance", () => ({ default: () => null }));

const detail = {
  answer_text: "Acme is recommended [S1].",
  mentioned: true,
  cited: true,
  recommended: true,
  incorrect: false,
  actions: [
    { priority: "P0", category: "content_gap", title: "Verify your profile", rationale: "Keep details current.", deep_link: "/dashboard/locations", effort: "low", evidence: {} },
  ],
  sources: [
    { id: "s1", label: "S1", position: 0, url: "https://example.com", title: "Acme listing", excerpt: "Acme is recommended", fetch_error: null },
  ],
  claims: [],
};

const copy = {
  verdict: "Strong public proof",
  strongProof: "Strong public proof",
  limitedProof: "Limited public proof",
  noProof: "No public proof yet",
  incorrectProof: "Public details need correction",
  decisionBrief: "Decision brief",
  answer: "Grounded answer",
  mentioned: "Mentioned",
  cited: "Cited",
  recommended: "Recommended",
  incorrect: "Incorrect",
  fixNext: "Fix next",
  evidenceSummary: (claims: number, sources: number) => `Evidence — ${claims} claims, ${sources} sources`,
  claim: "Claim",
  status: "Status",
  sources: "Sources",
  quote: "Quote",
  supported: "Supported",
  contradicted: "Contradicted",
  unsupported: "Unsupported",
  openSource: "Open source",
  noEvidence: "No evidence was saved for this run.",
};

describe("ResearchBrief", () => {
  it("puts the verdict, grounded answer, top fix and evidence disclosure first", () => {
    render(<ResearchBrief detail={detail as never} copy={copy as never} />);
    expect(screen.getByText("Strong public proof")).toBeInTheDocument();
    expect(screen.getByText(/Acme is recommended/)).toBeInTheDocument();
    expect(screen.getByText("Verify your profile")).toBeInTheDocument();
    expect(screen.getAllByText("Evidence — 0 claims, 1 sources")[1]).toBeVisible();
  });
});
