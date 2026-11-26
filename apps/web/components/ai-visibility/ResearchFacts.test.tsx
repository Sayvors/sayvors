import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/en";
import ResearchFacts from "./ResearchFacts";

describe("ResearchFacts", () => {
  it("shows owner-first evidence counts and explains irrelevant search hits", () => {
    render(
      <ResearchFacts
        copy={en.aiVisibility}
        coverage={{
          third_party_source_count: 0,
          owned_source_count: 2,
          validated_claim_count: 1,
          metrics: { platforms_found: 0, candidates_found: 10 },
        }}
      />,
    );
    expect(screen.getByText(en.aiVisibility.facts.noIndependentNote)).toBeInTheDocument();
    expect(screen.getAllByText(en.aiVisibility.facts.independentMentions).length).toBeGreaterThan(0);
    expect(screen.getAllByText(en.aiVisibility.facts.ownedPages).length).toBeGreaterThan(0);
    expect(screen.getAllByText(en.aiVisibility.facts.publicProfiles).length).toBeGreaterThan(0);
    expect(screen.getByText(en.aiVisibility.facts.verifiedFacts)).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("2").length).toBeGreaterThan(0);
    expect(screen.getByLabelText(en.aiVisibility.facts.chartTitle)).toBeInTheDocument();
    expect(screen.queryByText("10")).not.toBeInTheDocument();
  });

  it("renders evidence counts for older runs without detailed metrics", () => {
    render(
      <ResearchFacts
        copy={en.aiVisibility}
        coverage={{ third_party_source_count: 3, owned_source_count: 0, validated_claim_count: 2 }}
      />,
    );
    expect(screen.getByText("3 independent public pages mention your branch.")).toBeInTheDocument();
  });

  it("renders nothing when no evidence counts exist", () => {
    const { container } = render(
      <ResearchFacts copy={en.aiVisibility} coverage={{ source_count: 5 }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
