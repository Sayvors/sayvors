import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FactSource } from "./FactSource";

describe("FactSource", () => {
  it("names the source and its window", () => {
    render(
      <FactSource
        source="Google Business Profile"
        detail="last 30 days"
        note="synced 5m ago"
      />,
    );

    expect(screen.getByText("Google Business Profile")).toBeInTheDocument();
    expect(screen.getByText("last 30 days")).toBeInTheDocument();
    expect(screen.getByText("synced 5m ago")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders the verification link as a safe external tab", () => {
    render(
      <FactSource
        source="Google Business Profile"
        href="https://www.google.com/maps/place/?q=place_id:abc"
        linkLabel="Verify on Google Maps"
      />,
    );

    const link = screen.getByRole("link", { name: /verify on google maps/i });
    expect(link).toHaveAttribute(
      "href",
      "https://www.google.com/maps/place/?q=place_id:abc",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveTextContent("(opens in a new tab)");
  });

  it("fails closed on a script-capable href", () => {
    render(
      <FactSource
        source="Google Business Profile"
        href="javascript:alert(document.cookie)"
        linkLabel="Verify on Google Maps"
      />,
    );

    expect(screen.queryByRole("link")).toBeNull();
  });
});
