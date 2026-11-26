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
  evidence_coverage: {
    source_count: 2,
    validated_claim_count: 1,
    publishing_recommendations: [
      {
        platform: "Reddit",
        setup_url: "https://www.reddit.com/submit",
        reason: "Share useful expertise in relevant communities.",
      },
      {
        platform: "Medium",
        setup_url: "https://medium.com/new-story",
        reason: "Publish in-depth industry articles.",
      },
      {
        platform: "Substack",
        setup_url: "https://substack.com/start",
        reason: "Build a recurring customer newsletter.",
      },
    ],
  },
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
  howSearched: "How we searched",
  searchProvider: "Search provider",
  searchQuery: "Search query",
  searchResults: "Search results",
  sourcesFetched: "Sources fetched",
  thirdPartySources: "Third-party sources",
  ownedSources: "Owned sources",
  socialNotChecked: "Private social accounts are not checked",
  publishingChecklist: "Publishing checklist",
  publishingHint: "Official setup pages",
  platformCoverage: "Public platform coverage",
  foundPublic: "Found public profile",
  notFoundPublic: "No public profile found",
  unknownPublic: "Unknown",
  privateNote: "Private accounts are never accessed",
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
  it("shows business-specific publishing destinations without expanding search details", () => {
    render(<DecisionBrief detail={detail as never} copy={copy as never} />);
    expect(screen.getByText("Publishing checklist")).toBeVisible();
    expect(screen.getByRole("link", { name: "Reddit ↗" })).toHaveAttribute(
      "href",
      "https://www.reddit.com/submit",
    );
    expect(screen.getByRole("link", { name: "Medium ↗" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Substack ↗" })).toBeVisible();
  });

  it("shows the source domain beside each cited website", () => {
    render(<DecisionBrief detail={detail as never} copy={copy as never} />);
    expect(screen.getByText("example.com")).toBeVisible();
    expect(screen.getByText("failed.example")).toBeVisible();
  });

  it("does not render unsafe public-profile setup links", () => {
    render(
      <DecisionBrief
        detail={{
          ...detail,
          evidence_coverage: {
            ...detail.evidence_coverage,
            platforms: [
              {
                platform: "Untrusted profile",
                status: "not_found",
                setup_url: "javascript:alert(1)",
              },
            ],
          },
        } as never}
        copy={copy as never}
      />,
    );
    expect(screen.queryByRole("link", { name: "Publish publicly ↗" })).not.toBeInTheDocument();
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
