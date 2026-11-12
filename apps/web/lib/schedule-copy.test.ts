import { describe, it, expect } from "vitest";
import {
  mediaStatusLabel,
  goesLiveText,
  goesLiveWithinMinuteText,
  autoRemovesText,
  minutesLate,
  isNoticeablyLate,
} from "./schedule-copy";

describe("schedule-copy", () => {
  it("maps raw statuses to merchant copy", () => {
    expect(mediaStatusLabel("DRAFT")).toBe("In library");
    expect(mediaStatusLabel("SCHEDULED")).toBe("Scheduled");
    expect(mediaStatusLabel("PUBLISHED")).toBe("Live on Google");
    expect(mediaStatusLabel("FAILED")).toBe("Couldn't publish");
    expect(mediaStatusLabel(undefined)).toBe("In library");
    expect(mediaStatusLabel("WEIRD")).toBe("In library");
  });

  it("builds the promise sentence", () => {
    expect(goesLiveText("2026-11-13T07:00:00.000Z")).toBe("Goes live Fri, Nov 13 at 10:00 AM.");
    expect(goesLiveWithinMinuteText("2026-11-13T07:00:00.000Z")).toContain("usually within a minute");
    expect(goesLiveText(null)).toBe("");
    expect(goesLiveText("not-a-date")).toBe("");
  });

  it("builds the removal promise", () => {
    expect(autoRemovesText("2026-11-20T15:00:00.000Z")).toBe("Auto-removes on Fri, Nov 20.");
    expect(autoRemovesText("")).toBe("");
  });

  it("measures lateness", () => {
    const now = new Date("2026-11-13T07:10:00.000Z");
    expect(minutesLate("2026-11-13T07:00:00.000Z", now)).toBe(10);
    expect(minutesLate("2026-11-13T08:00:00.000Z", now)).toBeNull(); // not due yet
    expect(minutesLate(null, now)).toBeNull();
    expect(isNoticeablyLate("2026-11-13T07:00:00.000Z", now)).toBe(true);
    expect(isNoticeablyLate("2026-11-13T07:05:30.000Z", now)).toBe(false); // 4.5 min -> 4 minutes late
  });
});
