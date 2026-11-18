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
  /** Stable grouping key owned by the backend catalog. */
  section: string;
  section_label: string;
  answer: string[] | string | Record<string, unknown>;
  skipped: boolean;
  answer_source: "manual" | "google_confirmed";
  google_value: string | null;
}

export interface IntakeSection {
  key: string;
  label: string;
  answered: number;
  total: number;
  /** Includes skipped questions: a deferral is still work to do. */
  remaining: number;
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
  sections: IntakeSection[];
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

/** One card in the selectable grid. `tone: notSure` is styled as a decline,
 *  never as a recorded fact. */
export interface IntakeChoice {
  key: string;
  title: string;
  description?: string;
  badge?: string;
  tone?: "default" | "notSure";
}

export const NOT_SURE = "Not sure";

/**
 * Stored answer shapes vary: a chip array, a free-text string, or a legacy
 * `{ value }` object. Normalise once so the editor and the read-only table
 * cannot disagree about whether a question is answered.
 */
export function storedValues(answer: unknown): string[] {
  if (Array.isArray(answer)) return answer.map(String).filter(Boolean);
  if (typeof answer === "string") return answer.trim() ? [answer.trim()] : [];
  if (answer && typeof answer === "object") {
    const value = (answer as { value?: unknown }).value;
    if (Array.isArray(value)) return value.map(String).filter(Boolean);
    if (value != null && value !== "") return [String(value)];
  }
  return [];
}

/** Initial selections from the server answer + any Google confirmation. */
export function initialSelections(questions: IntakeQuestion[]): Selections {
  const out: Selections = {};
  for (const q of questions) {
    out[q.key] = {
      values: storedValues(q.answer),
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
 * Options for one question as typed grid choices. Google's value is included
 * once and flagged so the card can carry a "From Google" badge; "Not sure" is
 * always last and flagged so it can be styled as a decline.
 */
export function optionChoices(
  q: IntakeQuestion,
): { value: string; google: boolean; notSure: boolean }[] {
  const values = [...q.options];
  if (q.google_value && !values.includes(q.google_value)) values.push(q.google_value);
  const choices = values.map((value) => ({
    value,
    google: value === q.google_value,
    notSure: false,
  }));
  if (values.length && !values.includes(NOT_SURE)) {
    choices.push({ value: NOT_SURE, google: false, notSure: true });
  }
  return choices;
}

/** Render a stored answer as one readable line. `{}` and `[]` mean no answer. */
export function answerText(answer: unknown): string {
  return storedValues(answer).join(" · ");
}

/** A question still needs the owner: never answered, or explicitly deferred. */
export function isPending(q: IntakeQuestion): boolean {
  return q.skipped || answerText(q.answer) === "";
}

/** Unanswered and skipped questions, in catalog order. */
export function remainingQuestions(questions: IntakeQuestion[]): IntakeQuestion[] {
  return questions.filter(isPending);
}

/**
 * Questions grouped by the backend's section field, preserving catalog order
 * inside each group. `order` is the backend's canonical section order; keys it
 * does not mention are appended rather than dropped.
 */
export function sectionGroups(
  questions: IntakeQuestion[],
  order: string[] = [],
): { key: string; label: string; questions: IntakeQuestion[] }[] {
  const groups: { key: string; label: string; questions: IntakeQuestion[] }[] = [];
  const byKey = new Map<string, (typeof groups)[number]>();
  for (const q of questions) {
    const key = q.section || "offering";
    let group = byKey.get(key);
    if (!group) {
      group = { key, label: q.section_label || key, questions: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.questions.push(q);
  }
  if (!order.length) return groups;
  const rank = new Map(order.map((key, i) => [key, i]));
  return groups
    .map((group, i) => ({ group, i }))
    .sort((a, b) => {
      const ra = rank.get(a.group.key) ?? Number.MAX_SAFE_INTEGER;
      const rb = rank.get(b.group.key) ?? Number.MAX_SAFE_INTEGER;
      return ra === rb ? a.i - b.i : ra - rb;
    })
    .map(({ group }) => group);
}

/** Dashboard deep link into the shared flow, optionally at one question. */
export function intakeHref(section?: string, questionKey?: string): string {
  const params = new URLSearchParams();
  if (section) params.set("focus", section);
  if (questionKey) params.set("q", questionKey);
  const query = params.toString();
  return `/dashboard/business-intake${query ? `?${query}` : ""}`;
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
