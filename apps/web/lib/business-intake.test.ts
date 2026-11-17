import { describe, expect, it } from "vitest";

import {
  answeredCount,
  buildAnswersPayload,
  chipsFor,
  initialSelections,
  isAnswered,
  NOT_SURE,
  toggleChip,
  type IntakeQuestion,
} from "./business-intake";

const q = (over: Partial<IntakeQuestion> = {}): IntakeQuestion => ({
  key: "dietary",
  label: "Dietary options",
  source: "ask",
  options: ["Halal", "Vegan"],
  multiple: true,
  fact_key: "dietary",
  answer: [],
  skipped: false,
  google_value: null,
  ...over,
});

describe("chip semantics", () => {
  it("multi-select accumulates and toggles off", () => {
    expect(toggleChip([], "Halal", true)).toEqual(["Halal"]);
    expect(toggleChip(["Halal"], "Vegan", true)).toEqual(["Halal", "Vegan"]);
    expect(toggleChip(["Halal", "Vegan"], "Halal", true)).toEqual(["Vegan"]);
  });

  it("single-select replaces rather than accumulates", () => {
    expect(toggleChip(["Halal"], "Vegan", false)).toEqual(["Vegan"]);
    expect(toggleChip(["Vegan"], "Vegan", false)).toEqual([]);
  });

  it("offers the Google value and 'Not sure' without duplicating them", () => {
    const chips = chipsFor(q({ google_value: "Yes, delivery" }));
    expect(chips).toContain("Yes, delivery");
    expect(chips.filter((c) => c === NOT_SURE)).toHaveLength(1);
    expect(chipsFor(q({ options: [], google_value: null }))).toEqual([]);
  });
});

describe("answer state", () => {
  it("restores a stored answer", () => {
    const s = initialSelections([q({ answer: ["Halal"] })]);
    expect(s.dietary.values).toEqual(["Halal"]);
    expect(isAnswered(s.dietary)).toBe(true);
  });

  it("treats skipped and empty as unanswered", () => {
    expect(isAnswered({ values: [], skipped: true, source: "manual" })).toBe(false);
    expect(isAnswered({ values: [], skipped: false, source: "manual" })).toBe(false);
    expect(answeredCount([q()], initialSelections([q()]))).toBe(0);
  });
});

describe("PUT payload", () => {
  it("omits unanswered questions and records Google confirmations", () => {
    const questions = [q(), q({ key: "delivery", options: [] })];
    const selections = initialSelections(questions);
    selections.dietary = { values: ["Halal"], skipped: false, source: "manual" };
    selections.delivery = {
      values: ["Yes, delivery"], skipped: false, source: "google_confirmed",
    };

    expect(buildAnswersPayload(questions, selections)).toEqual([
      { question_key: "dietary", answer: ["Halal"], skipped: false, source: "manual" },
      {
        question_key: "delivery",
        answer: ["Yes, delivery"],
        skipped: false,
        source: "google_confirmed",
      },
    ]);
  });

  it("sends an explicit skipped row so 'asked but declined' is not lost", () => {
    const questions = [q()];
    const selections = initialSelections(questions);
    selections.dietary = { values: [], skipped: true, source: "manual" };
    expect(buildAnswersPayload(questions, selections)).toEqual([
      { question_key: "dietary", answer: [], skipped: true, source: "manual" },
    ]);
  });
});
