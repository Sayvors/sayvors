import { describe, expect, it } from "vitest";

import {
  rankStaff,
  sentimentShares,
  staffScore,
  staffVerdict,
  type StaffSummaryLike,
} from "./staff-performance";

const row = (over: Partial<StaffSummaryLike> = {}): StaffSummaryLike => ({
  staff_member_id: over.staff_member_id ?? "id",
  name: over.name ?? "Name",
  mentions: over.mentions ?? 0,
  positive: over.positive ?? 0,
  neutral: over.neutral ?? 0,
  negative: over.negative ?? 0,
  avg_rating: over.avg_rating ?? null,
  prior_mentions: over.prior_mentions ?? 0,
  trend: over.trend ?? "flat",
});

describe("staff sentiment shares", () => {
  it("splits 10/5/5 into rounded percentages", () => {
    expect(sentimentShares(row({ positive: 10, neutral: 5, negative: 5 }))).toEqual({
      positive: 50, neutral: 25, negative: 25,
    });
  });

  it("returns zeroed shares when nobody mentioned the employee", () => {
    expect(sentimentShares(row({ mentions: 0 }))).toEqual({ positive: 0, neutral: 0, negative: 0 });
  });
});

describe("staff score", () => {
  it("is positive for mostly praise, negative for mostly criticism", () => {
    expect(staffScore(row({ positive: 9, neutral: 0, negative: 1 }))).toBe(80);
    expect(staffScore(row({ positive: 1, neutral: 0, negative: 9 }))).toBe(-80);
    expect(staffScore(row({ positive: 5, neutral: 5, negative: 0 }))).toBe(50);
  });

  it("does not promote an unmentioned employee to the top", () => {
    expect(staffScore(row({ mentions: 0 }))).toBe(0);
  });
});

describe("staff verdict", () => {
  it("labels a clear star 'great'", () => {
    expect(staffVerdict(row({ mentions: 10, positive: 8, neutral: 2, negative: 0 }))).toBe("great");
  });

  it("labels heavy criticism 'watch'", () => {
    expect(staffVerdict(row({ mentions: 10, positive: 3, neutral: 2, negative: 5 }))).toBe("watch");
  });

  it("labels a solid majority 'good' and an even split 'mixed'", () => {
    expect(staffVerdict(row({ mentions: 10, positive: 6, neutral: 3, negative: 1 }))).toBe("good");
    expect(staffVerdict(row({ mentions: 10, positive: 4, neutral: 3, negative: 3 }))).toBe("mixed");
  });

  it("labels an unmentioned employee 'new'", () => {
    expect(staffVerdict(row({ mentions: 0 }))).toBe("new");
  });
});

describe("rankStaff", () => {
  it("puts the best sentiment first and keeps stable ties", () => {
    const great = row({ staff_member_id: "a", name: "A", positive: 10 });
    const watch = row({ staff_member_id: "b", name: "B", negative: 10 });
    const neutral = row({ staff_member_id: "c", name: "C", neutral: 10 });
    expect(rankStaff([watch, neutral, great]).map((r) => r.staff_member_id)).toEqual(["a", "c", "b"]);
  });

  it("does not mutate the input", () => {
    const input = [row({ positive: 1 }), row({ negative: 1 })];
    rankStaff(input);
    expect(input[0].positive).toBe(1);
  });
});
