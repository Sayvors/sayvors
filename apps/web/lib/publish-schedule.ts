/*
 * Date rules for scheduling a post, shared by the composer and the details
 * editor. Values are the strings a datetime-local input produces
 * ("YYYY-MM-DDTHH:MM", the browser's local wall-clock time). An empty value
 * means the date is not set.
 */

export type WindowError = "scheduleInPast" | "removeBeforePublish" | "eventEnd";

/** The value a datetime-local input takes for a local Date. */
export function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** The earliest value a datetime-local input may hold: the current minute.
 * The pickers start at now so a past time cannot be picked by accident. */
export function minLocalInput(now: Date = new Date()): string {
  return toLocalInput(now);
}

/**
 * The first problem with the dates, or null when they can be saved.
 *
 * - A schedule must be in the future.
 * - A removal must come after the time the post goes out: its schedule, or
 *   now when the post goes out immediately.
 * - An event must end after it starts.
 */
export function checkWindow(input: {
  scheduleAt: string;
  removeAt: string;
  startDate: string;
  endDate: string;
  now?: Date;
}): WindowError | null {
  const nowMs = (input.now ?? new Date()).getTime();
  const scheduleMs = input.scheduleAt ? new Date(input.scheduleAt).getTime() : null;
  if (scheduleMs !== null && scheduleMs <= nowMs) return "scheduleInPast";
  if (input.removeAt) {
    const publishMs = scheduleMs ?? nowMs;
    if (new Date(input.removeAt).getTime() <= publishMs) return "removeBeforePublish";
  }
  if (input.startDate && input.endDate) {
    if (new Date(input.endDate).getTime() <= new Date(input.startDate).getTime()) {
      return "eventEnd";
    }
  }
  return null;
}
