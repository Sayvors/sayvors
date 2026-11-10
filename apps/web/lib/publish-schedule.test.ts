import { describe, expect, it } from "vitest";
import { checkWindow, minLocalInput, toLocalInput } from "./publish-schedule";

const NOW = new Date(2026, 10, 10, 12, 0);

describe("toLocalInput", () => {
  it("formats the local wall-clock time the input expects", () => {
    expect(toLocalInput(new Date(2026, 10, 9, 7, 5))).toBe("2026-11-09T07:05");
  });
});

describe("minLocalInput", () => {
  it("is the current minute, so the picker starts at now", () => {
    expect(minLocalInput(NOW)).toBe("2026-11-10T12:00");
  });
});

describe("checkWindow", () => {
  const base = { scheduleAt: "", removeAt: "", startDate: "", endDate: "", now: NOW };

  it("accepts no dates at all: publish now, keep forever", () => {
    expect(checkWindow(base)).toBeNull();
  });

  it("refuses a schedule in the past", () => {
    expect(checkWindow({ ...base, scheduleAt: "2026-11-10T11:00" })).toBe("scheduleInPast");
  });

  it("accepts a schedule in the future", () => {
    expect(checkWindow({ ...base, scheduleAt: "2026-11-11T09:00" })).toBeNull();
  });

  it("refuses a removal before the post goes out", () => {
    expect(checkWindow({ ...base, removeAt: "2026-11-10T11:59" })).toBe("removeBeforePublish");
    expect(
      checkWindow({ ...base, scheduleAt: "2026-11-12T09:00", removeAt: "2026-11-11T09:00" }),
    ).toBe("removeBeforePublish");
  });

  it("accepts a removal after the scheduled time", () => {
    expect(
      checkWindow({ ...base, scheduleAt: "2026-11-11T09:00", removeAt: "2026-11-15T09:00" }),
    ).toBeNull();
  });

  it("refuses an event that ends before it starts", () => {
    expect(
      checkWindow({ ...base, startDate: "2026-11-20T10:00", endDate: "2026-11-20T09:00" }),
    ).toBe("eventEnd");
  });
});
