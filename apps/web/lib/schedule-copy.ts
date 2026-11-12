// schedule-copy.ts
//
// Merchant-facing wording for scheduled publishing. The rule: never name who
// runs the clock (Sayvors vs Google) — always state the promise the merchant
// can trust, in their own language and timezone. The only honesty margin is a
// plain "usually within a minute" for surfaces whose publish fires from our
// worker (media gallery/profile/banner), since Google has no native schedule
// for those.

export type MediaStatus = "DRAFT" | "SCHEDULED" | "PUBLISHED" | "FAILED";

/** Status pill text shown to merchants, never the raw backend state. */
export const MEDIA_STATUS_LABEL: Record<MediaStatus, string> = {
  DRAFT: "In library",
  SCHEDULED: "Scheduled",
  PUBLISHED: "Live on Google",
  FAILED: "Couldn't publish",
};

export function mediaStatusLabel(status: string | undefined): string {
  return MEDIA_STATUS_LABEL[(status as MediaStatus) ?? "DRAFT"] ?? "In library";
}

function fmt(iso: string | null | undefined, opts?: { time?: boolean }): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    const date = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    if (opts?.time === false) return date;
    const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return `${date} at ${time}`;
  } catch {
    return d.toDateString();
  }
}

/** "Goes live Fri, Nov 13 at 10:00 AM." (post — exact). */
export function goesLiveText(iso: string | null | undefined): string {
  const f = fmt(iso);
  return f ? `Goes live ${f}.` : "";
}

/** "Goes live Fri, Nov 13 at 10:00 AM — usually within a minute of that time." */
export function goesLiveWithinMinuteText(iso: string | null | undefined): string {
  const f = fmt(iso);
  return f ? `Goes live ${f} — usually within a minute of that time.` : "";
}

/** "Auto-removes on Fri, Nov 20." */
export function autoRemovesText(iso: string | null | undefined): string {
  const f = fmt(iso, { time: false });
  return f ? `Auto-removes on ${f}.` : "";
}

/** Minutes past the scheduled time, or null when not scheduled / not yet due. */
export function minutesLate(scheduledIso: string | null | undefined, now: Date = new Date()): number | null {
  if (!scheduledIso) return null;
  const at = new Date(scheduledIso);
  if (Number.isNaN(at.getTime())) return null;
  const mins = Math.floor((now.getTime() - at.getTime()) / 60000);
  return mins >= 0 ? mins : null;
}

/** True once a scheduled item is overdue by 5+ minutes (still not live). */
export function isNoticeablyLate(scheduledIso: string | null | undefined, now: Date = new Date()): boolean {
  const mins = minutesLate(scheduledIso, now);
  return mins !== null && mins >= 5;
}
