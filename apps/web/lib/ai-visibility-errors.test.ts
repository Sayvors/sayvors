import { describe, expect, it } from "vitest";
import { researchErrorMessage } from "./ai-visibility-errors";

describe("researchErrorMessage", () => {
  it("never shows a backend policy code", () => {
    const message = researchErrorMessage("retry_limit_reached");
    expect(message).not.toContain("retry_limit_reached");
    expect(message).toContain("slot opens");
  });

  it("passes through human sentences", () => {
    expect(researchErrorMessage("Search provider unavailable.")).toBe(
      "Search provider unavailable.",
    );
  });
});
