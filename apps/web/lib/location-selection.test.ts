import { describe, expect, it } from "vitest";
import { preferredLocationId } from "./location-selection";

describe("preferredLocationId", () => {
  it("opens the first verified branch instead of an unverified draft", () => {
    expect(
      preferredLocationId([
        { id: "draft", is_verified: false },
        { id: "live", is_verified: true },
      ]),
    ).toBe("live");
  });

  it("keeps the first branch when every branch is verified", () => {
    expect(
      preferredLocationId([
        { id: "first", is_verified: true },
        { id: "second", is_verified: true },
      ]),
    ).toBe("first");
  });

  it("falls back to the first branch when none are verified", () => {
    expect(
      preferredLocationId([
        { id: "first", is_verified: false },
        { id: "second", is_verified: false },
      ]),
    ).toBe("first");
  });

  it("treats a missing verification field as unverified", () => {
    expect(
      preferredLocationId([
        { id: "unknown" },
        { id: "live", is_verified: true },
      ]),
    ).toBe("live");
  });

  it("returns null for an empty account", () => {
    expect(preferredLocationId([])).toBeNull();
  });
});
