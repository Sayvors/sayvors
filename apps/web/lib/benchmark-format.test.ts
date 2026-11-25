import { describe, expect, it } from "vitest";

import {
  formatGap,
  formatPercent,
  formatRating,
} from "./benchmark-format";

describe("benchmark number formatting", () => {
  it("rounds percentages to one decimal without floating-point noise", () => {
    expect(formatPercent(66.66666666666666)).toBe("66.7%");
    expect(formatPercent(76.31578947368422)).toBe("76.3%");
    expect(formatPercent(0.8771929824561403)).toBe("0.9%");
    expect(formatPercent(50)).toBe("50%");
    expect(formatPercent(0)).toBe("0%");
  });

  it("keeps missing percentages blank", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(Number.NaN)).toBe("—");
  });

  it("formats ratings with consistent precision", () => {
    expect(formatRating(4.7)).toBe("4.70 ★");
    expect(formatRating(4.674)).toBe("4.67 ★");
    expect(formatRating(null)).toBe("—");
  });

  it("formats gaps with the same unit as the row", () => {
    expect(formatGap(111, "count")).toBe("+111");
    expect(formatGap(-1, "count")).toBe("−1");
    expect(formatGap(9.649999, "percent")).toBe("+9.6%");
    expect(formatGap(-0.877192, "percent")).toBe("−0.9%");
    expect(formatGap(0.034, "rating")).toBe("+0.03 ★");
  });

  it("suppresses gaps that round to zero", () => {
    expect(formatGap(0.01, "count")).toBeNull();
    expect(formatGap(0.001, "percent")).toBeNull();
    expect(formatGap(0.001, "rating")).toBeNull();
  });
});
