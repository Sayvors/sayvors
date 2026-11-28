import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EvidenceDrawer from "./EvidenceDrawer";

const detail = {
  claims: [
    { claim: "Acme is licensed", quote: "Acme is licensed", source_ids: ["S1"], status: "supported" as const },
  ],
  sources: [
    { id: "s1", label: "S1", position: 0, url: "https://example.com", title: "Acme listing", excerpt: "Acme is licensed", fetch_error: null },
    { id: "s2", label: "S2", position: 1, url: "https://news.example", title: "Coverage", excerpt: null, fetch_error: "timeout" },
  ],
};

const copy = {
  evidenceSummary: (claims: number, sources: number) => `Evidence — ${claims} claim, ${sources} sources`,
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

describe("EvidenceDrawer", () => {
  it("renders one labeled disclosure with a semantic claim table and source list", () => {
    render(<EvidenceDrawer detail={detail as never} copy={copy as never} />);
    expect(screen.getByText("Evidence — 1 claim, 2 sources")).toBeVisible();
    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Claim" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Quote" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "S1 · Acme listing" })).toHaveAttribute("href", "https://example.com");
    expect(screen.getByText(/timeout/)).toBeInTheDocument();
  });
});
