/** Ready-made hours presets.
 *
 * A template fills the form; the merchant still presses Save. Nothing here
 * talks to the API, so applying a template can never change Google on its
 * own — the save button is what publishes it.
 *
 * The names are i18n keys (`nameKey`) so the UI can show them in the
 * merchant's language while the pattern stays machine-readable.
 */

export const HOURS_DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export type DayName = (typeof HOURS_DAYS)[number];

export type HoursPattern = Record<
  string,
  { open: string; close: string; closed: boolean; all_day?: boolean }
>;

export interface HoursTemplate {
  id: string;
  nameKey: string;
  hours: HoursPattern;
}

export interface SpecialHoursTemplate {
  id: string;
  nameKey: string;
  /** The hours text as the form stores it ("09:00 - 17:00", or "Closed"). */
  hours: string;
  reason: string;
  /** How many days the preset spans by default. */
  days: number;
}

export interface MoreHoursTemplate {
  id: string;
  nameKey: string;
  type: string;
  open: string;
  close: string;
}

const WEEKDAYS: DayName[] = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
];
const ALL_DAYS: DayName[] = [...HOURS_DAYS];

/** A week where the given days open at `open` and close at `close`. */
function pattern(
  days: DayName[],
  open: string,
  close: string,
  allDay = false,
): HoursPattern {
  const out: HoursPattern = {};
  for (const day of HOURS_DAYS) {
    const on = days.includes(day);
    out[day] = on
      ? { open, close, closed: false, all_day: allDay }
      : { open: "", close: "", closed: true, all_day: false };
  }
  return out;
}

/** Open every day, all day (00:00 to 24:00). */
function allDayPattern(): HoursPattern {
  const out: HoursPattern = {};
  for (const day of HOURS_DAYS) {
    out[day] = { open: "00:00", close: "24:00", closed: false, all_day: true };
  }
  return out;
}

export const HOURS_TEMPLATES: HoursTemplate[] = [
  { id: "open-24h", nameKey: "templateOpen24h", hours: allDayPattern() },
  { id: "nine-to-six", nameKey: "templateNineToSix", hours: pattern(ALL_DAYS, "09:00", "18:00") },
  { id: "nine-to-five-weekdays", nameKey: "templateNineToFiveWeekdays", hours: pattern(WEEKDAYS, "09:00", "17:00") },
  { id: "ten-to-four-weekdays", nameKey: "templateTenToFourWeekdays", hours: pattern(WEEKDAYS, "10:00", "16:00") },
  { id: "ten-to-ten-daily", nameKey: "templateTenToTenDaily", hours: pattern(ALL_DAYS, "10:00", "22:00") },
  { id: "eight-to-six-daily", nameKey: "templateEightToSixDaily", hours: pattern(ALL_DAYS, "08:00", "18:00") },
];

export const SPECIAL_HOURS_TEMPLATES: SpecialHoursTemplate[] = [
  // Iftar to Suhoor — the hours a Saudi business keeps through Ramadan.
  { id: "ramadan", nameKey: "templateRamadan", hours: "16:00 - 02:00", reason: "Ramadan", days: 30 },
  { id: "eid", nameKey: "templateEid", hours: "Closed", reason: "Eid", days: 3 },
  { id: "national-day", nameKey: "templateNationalDay", hours: "Closed", reason: "National Day", days: 1 },
  { id: "working-day", nameKey: "templateWorkingDay", hours: "09:00 - 17:00", reason: "Working day", days: 1 },
  { id: "half-day", nameKey: "templateHalfDay", hours: "09:00 - 13:00", reason: "Half day", days: 1 },
  { id: "late-opening", nameKey: "templateLateOpening", hours: "12:00 - 21:00", reason: "Late opening", days: 1 },
];

export const MORE_HOURS_TEMPLATES: MoreHoursTemplate[] = [
  { id: "breakfast", nameKey: "templateBreakfast", type: "Brunch", open: "07:00", close: "11:00" },
  { id: "lunch", nameKey: "templateLunch", type: "Lunch", open: "12:00", close: "15:00" },
  { id: "dinner", nameKey: "templateDinner", type: "Dinner", open: "18:00", close: "23:00" },
  { id: "happy-hour", nameKey: "templateHappyHour", type: "Happy Hour", open: "16:00", close: "19:00" },
  { id: "delivery", nameKey: "templateDelivery", type: "Delivery", open: "10:00", close: "22:00" },
  { id: "takeout", nameKey: "templateTakeout", type: "Takeout", open: "11:00", close: "23:00" },
];

/** "YYYY-MM-DD" shifted by `days` calendar days. */
export function addDays(date: string, days: number): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return date;
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

/** Apply a regular-hours preset over the whole week. */
export function applyHoursTemplate(
  current: HoursPattern,
  template: HoursTemplate,
): HoursPattern {
  const next: HoursPattern = {};
  for (const day of HOURS_DAYS) {
    next[day] = template.hours[day] ?? {
      open: "",
      close: "",
      closed: true,
      all_day: false,
    };
  }
  // Keep anything the merchant already set for a day the preset leaves open
  // but did not define (a preset always defines every day, so this is a
  // no-op today; it keeps the helper honest for future presets).
  for (const [day, value] of Object.entries(current)) {
    if (!(day in next) && value) next[day] = value;
  }
  return next;
}

export interface SpecialHoursEntry {
  date: string;
  hours: string;
  reason: string;
}

/** Apply a special-hours preset across a date range.
 *
 * Entries on the covered dates are replaced; every other entry the merchant
 * added is kept.
 */
export function applySpecialHoursTemplate(
  current: SpecialHoursEntry[],
  template: SpecialHoursTemplate,
  startDate: string,
  days: number,
): SpecialHoursEntry[] {
  const count = Math.max(1, Math.min(60, Math.floor(days) || 1));
  const covered = new Set<string>();
  const added: SpecialHoursEntry[] = [];
  for (let i = 0; i < count; i += 1) {
    const date = addDays(startDate, i);
    covered.add(date);
    added.push({ date, hours: template.hours, reason: template.reason });
  }
  const kept = current.filter((entry) => !covered.has(entry.date));
  return [...kept, ...added].sort((a, b) => a.date.localeCompare(b.date));
}

/** Apply a more-hours preset, replacing one of the same type. */
export function applyMoreHoursTemplate(
  current: { type: string; open: string; close: string }[],
  template: MoreHoursTemplate,
): { type: string; open: string; close: string }[] {
  const kept = current.filter((entry) => entry.type !== template.type);
  return [...kept, { type: template.type, open: template.open, close: template.close }];
}
