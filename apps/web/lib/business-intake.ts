/**
 * Pure helpers for the business-intake cascade.
 *
 * Kept out of the component so the chip logic (single vs multi select,
 * "Not sure", Google confirmations) is unit-testable and cannot silently
 * disagree with what the API receives.
 */

export interface IntakeQuestion {
  key: string;
  label: string;
  source: "google" | "google_partial" | "ask";
  options: string[];
  multiple: boolean;
  fact_key: string;
  answer: string[] | string | Record<string, unknown>;
  skipped: boolean;
  answer_source: "manual" | "google_confirmed";
  google_value: string | null;
}

export interface IntakeResponse {
  vertical_key: string | null;
  vertical_label: string | null;
  sub_focus: string | null;
  sub_focuses: { key: string; label: string }[];
  verticals: {
    key: string;
    label: string;
    sub_focuses: { key: string; label: string }[];
  }[];
  questions: IntakeQuestion[];
  answered: number;
  skipped: number;
  total: number;
  google_suggestion: {
    vertical_key: string;
    vertical_label: string;
    google_category: string | null;
  } | null;
}

export interface Selection {
  values: string[];
  skipped: boolean;
  source: "manual" | "google_confirmed";
}

export type Selections = Record<string, Selection>;

export const NOT_SURE = "Not sure";

/** Initial selections from the server answer + any Google confirmation. */
export function initialSelections(questions: IntakeQuestion[]): Selections {
  const out: Selections = {};
  for (const q of questions) {
    const stored = Array.isArray(q.answer)
      ? q.answer
      : typeof q.answer === "string" && q.answer
        ? [q.answer]
        : [];
    out[q.key] = {
      values: stored,
      skipped: Boolean(q.skipped),
      // A Google-confirmed value is stored with its normal source; the UI
      // passes source explicitly on save when the owner taps it.
      source: "manual",
    };
  }
  return out;
}

/** Toggle one chip. Single-select answers replace rather than accumulate. */
export function toggleChip(current: string[], chip: string, multiple: boolean): string[] {
  if (!multiple) return current.includes(chip) ? [] : [chip];
  return current.includes(chip)
    ? current.filter((v) => v !== chip)
    : [...current, chip];
}

/**
 * Chip set shown for one question. "Not sure" is appended so an owner can
 * honestly decline instead of guessing — it is stored as `skipped`, never
 * as a fact.
 */
export function chipsFor(q: IntakeQuestion): string[] {
  const options = [...q.options];
  if (q.google_value && !options.includes(q.google_value)) {
    options.push(q.google_value);
  }
  if (options.length && !options.includes(NOT_SURE)) options.push(NOT_SURE);
  return options;
}

export function isAnswered(s: Selection | undefined): boolean {
  return Boolean(s && !s.skipped && s.values.length > 0);
}

export function answeredCount(questions: IntakeQuestion[], selections: Selections): number {
  return questions.filter((q) => isAnswered(selections[q.key])).length;
}

/** The exact PUT body. Unknown keys and unanswered questions are omitted. */
export function buildAnswersPayload(
  questions: IntakeQuestion[],
  selections: Selections,
): { question_key: string; answer: string[]; skipped: boolean; source: string }[] {
  return questions.flatMap((q) => {
    const s = selections[q.key];
    if (!s || (!s.skipped && s.values.length === 0)) return [];
    return [{
      question_key: q.key,
      answer: s.skipped ? [] : s.values,
      skipped: s.skipped,
      source: s.source,
    }];
  });
}
