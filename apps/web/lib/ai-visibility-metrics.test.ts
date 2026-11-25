import { describe, expect, it } from "vitest";
import { formatRate, isActiveStatus } from "./ai-visibility-metrics";

describe("AI visibility metrics", () => {
  it("never turns missing evidence into zero", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(0)).toBe("0.0%");
    expect(formatRate(66.666)).toBe("66.7%");
    expect(formatRate(100)).toBe("100.0%");
  });

  it("recognizes every active run stage", () => {
    for (const status of ["queued", "searching", "fetching", "reading", "validating", "writing"]) {
      expect(isActiveStatus(status)).toBe(true);
    }
  });

  it("does not treat terminal or unknown states as active", () => {
    for (const status of ["completed", "failed", "insufficient_evidence", "ambiguous", "unknown", ""]) {
      expect(isActiveStatus(status)).toBe(false);
    }
  });
});
