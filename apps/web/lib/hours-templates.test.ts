import { describe, expect, it } from "vitest";

import {
  HOURS_TEMPLATES,
  MORE_HOURS_TEMPLATES,
  SPECIAL_HOURS_TEMPLATES,
  addDays,
  applyHoursTemplate,
  applyMoreHoursTemplate,
  applySpecialHoursTemplate,
} from "./hours-templates";

describe("hours templates", () => {
  it("fills every day of the week from a preset", () => {
    const template = HOURS_TEMPLATES.find((t) => t.id === "nine-to-five-weekdays");
    expect(template).toBeDefined();
    const hours = applyHoursTemplate({}, template!);
    expect(hours.Monday).toEqual({ open: "09:00", close: "17:00", closed: false, all_day: false });
    expect(hours.Saturday.closed).toBe(true);
    expect(hours.Sunday.closed).toBe(true);
  });

  it("has an all-day preset that never closes", () => {
    const template = HOURS_TEMPLATES.find((t) => t.id === "open-24h");
    const hours = applyHoursTemplate({}, template!);
    for (const day of Object.values(hours)) {
      expect(day.closed).toBe(false);
      expect(day.all_day).toBe(true);
      expect(day.close).toBe("24:00");
    }
  });

  it("shifts a date by calendar days", () => {
    expect(addDays("2026-03-19", 0)).toBe("2026-03-19");
    expect(addDays("2026-03-19", 1)).toBe("2026-03-20");
    // Month end rolls into the next month.
    expect(addDays("2026-03-31", 1)).toBe("2026-04-01");
  });

  it("spans a special-hours preset across the requested days", () => {
    const template = SPECIAL_HOURS_TEMPLATES.find((t) => t.id === "ramadan");
    expect(template).toBeDefined();
    const entries = applySpecialHoursTemplate([], template!, "2026-02-18", 3);
    expect(entries).toHaveLength(3);
    expect(entries[0]).toEqual({ date: "2026-02-18", hours: "16:00 - 02:00", reason: "Ramadan" });
    expect(entries[2].date).toBe("2026-02-20");
  });

  it("keeps the merchant's other special-hours entries", () => {
    const template = SPECIAL_HOURS_TEMPLATES.find((t) => t.id === "eid")!;
    const current = [
      { date: "2026-02-18", hours: "09:00 - 17:00", reason: "old" },
      { date: "2026-04-01", hours: "10:00 - 12:00", reason: "keep me" },
    ];
    const entries = applySpecialHoursTemplate(current, template, "2026-02-18", 2);
    // The 18th is replaced, the 19th is added, the 1st of April is untouched.
    expect(entries).toHaveLength(3);
    expect(entries.find((e) => e.date === "2026-02-18")?.reason).toBe("Eid");
    expect(entries.find((e) => e.date === "2026-02-19")?.reason).toBe("Eid");
    expect(entries.find((e) => e.date === "2026-04-01")?.reason).toBe("keep me");
  });

  it("replaces a more-hours entry of the same type", () => {
    const template = MORE_HOURS_TEMPLATES.find((t) => t.id === "lunch")!;
    const current = [
      { type: "Lunch", open: "12:00", close: "14:00" },
      { type: "Dinner", open: "18:00", close: "22:00" },
    ];
    const entries = applyMoreHoursTemplate(current, template);
    expect(entries).toHaveLength(2);
    expect(entries.find((e) => e.type === "Lunch")).toEqual({
      type: "Lunch",
      open: "12:00",
      close: "15:00",
    });
    expect(entries.find((e) => e.type === "Dinner")).toBeDefined();
  });
});
