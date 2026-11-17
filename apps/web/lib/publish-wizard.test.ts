import { describe, expect, it } from "vitest";

import {
  isTextFormat,
  needsMessageStep,
  stepNav,
  wizardSteps,
} from "./publish-wizard";

describe("publish wizard step rules", () => {
  it("classifies image surfaces vs text formats", () => {
    for (const method of ["profile", "banner", "gallery", "reel", "status", "story"]) {
      expect(isTextFormat(method), method).toBe(false);
    }
    for (const method of ["post", "update", "event", "offer"]) {
      expect(isTextFormat(method), method).toBe(true);
    }
  });

  it("skips the message step when only image surfaces are selected", () => {
    expect(needsMessageStep(["profile"])).toBe(false);
    const steps = wizardSteps(["profile", "banner", "gallery"]);
    expect(steps.map((s) => s.id)).toEqual(["media", "where", "when"]);
  });

  it("shows the message step for a single text format", () => {
    expect(needsMessageStep(["update"])).toBe(true);
    expect(wizardSteps(["update"]).map((s) => s.id)).toEqual([
      "media", "where", "message", "when",
    ]);
  });

  it("shows the message step in a mixed selection — caption is never silently dropped", () => {
    // A banner + update publish must still ask for the update's caption.
    expect(wizardSteps(["banner", "update"]).map((s) => s.id)).toEqual([
      "media", "where", "message", "when",
    ]);
  });

  it("defaults to no message step for an empty selection", () => {
    expect(wizardSteps([]).map((s) => s.id)).toEqual(["media", "where", "when"]);
  });

  it("numbers steps dynamically — 3 steps when message is skipped", () => {
    const steps = wizardSteps(["banner"]);
    expect(stepNav(steps, "media").number).toBe(1);
    expect(stepNav(steps, "where").number).toBe(2);
    const when = stepNav(steps, "when");
    expect(when.number).toBe(3);
    expect(when.total).toBe(3);
    expect(when.next).toBeNull();
  });

  it("numbers steps dynamically — 4 steps when message is shown", () => {
    const steps = wizardSteps(["update"]);
    expect(stepNav(steps, "where").next).toBe("message");
    expect(stepNav(steps, "message").number).toBe(3);
    expect(stepNav(steps, "when").number).toBe(4);
    expect(stepNav(steps, "when").previous).toBe("message");
  });

  it("navigates back from the first step to nowhere", () => {
    const steps = wizardSteps(["update"]);
    expect(stepNav(steps, "media").previous).toBeNull();
  });

  it("labels every step for both locales' copy keys", () => {
    const expected = ["stepMedia", "stepWhere", "stepMessage", "stepWhen"];
    for (const step of wizardSteps(["update", "banner"])) {
      expect(expected).toContain(step.labelKey);
    }
  });

  it("derives step ids, never raw positions, so skipping is stable", () => {
    // Media-only: "when" is the 3rd step with no message in between.
    const imageOnly = wizardSteps(["gallery"]);
    expect(imageOnly.map((s) => s.id)).toEqual(["media", "where", "when"]);
    expect(stepNav(imageOnly, "when").number).toBe(3);
    expect(stepNav(imageOnly, "when").previous).toBe("where");

    // Adding a text format inserts message before "when" without changing ids.
    const mixed = wizardSteps(["gallery", "update"]);
    expect(stepNav(mixed, "when").number).toBe(4);
    expect(stepNav(mixed, "when").previous).toBe("message");
  });
});
