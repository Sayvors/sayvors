import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/en";
import ResearchFacts from "./ResearchFacts";

describe("ResearchFacts", () => {
  it("shows the stored counters as large facts", () => {
    render(
      <ResearchFacts
        copy={en.aiVisibility}
        coverage={{
          validated_claim_count: 4,
          metrics: {
            candidates_found: 1234,
            pages_read: 6,
            pages_failed: 1,
            links_found: 87,
            words_read: 4210,
            domains_found: 9,
            brand_mentions: 2,
          },
        }}
      />,
    );
    expect(screen.getAllByText("1,234").length).toBeGreaterThan(0);
    expect(screen.getAllByText("87").length).toBeGreaterThan(0);
    expect(screen.getAllByText("4,210").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2").length).toBeGreaterThan(0);
    expect(screen.getByText(en.aiVisibility.facts.linksFound)).toBeInTheDocument();
    expect(screen.getByText("failed to open: 1")).toBeInTheDocument();
    expect(screen.getByLabelText(en.aiVisibility.facts.chartTitle)).toBeInTheDocument();
  });

  it("renders nothing for runs stored before counters existed", () => {
    const { container } = render(
      <ResearchFacts copy={en.aiVisibility} coverage={{ source_count: 5 }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
