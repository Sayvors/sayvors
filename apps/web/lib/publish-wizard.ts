/**
 * Publish-composer wizard step rules.
 *
 * The message step is conditional: a profile picture, banner (Promotion) or
 * gallery item is an image surface and carries no caption or description.
 * A feed text format (update/post/event/offer/story) does. Deriving the step
 * list from the *selected methods* — rather than from a hard-coded "update"
 * name — keeps a mixed publish (e.g. banner + update) correct: if any format
 * carries text, the message step appears.
 */
export type WizardStepId = "media" | "where" | "message" | "when";

export interface WizardStepDef {
  id: WizardStepId;
  /** Key under `t.publish.composer.wizard` in both locales. */
  labelKey: "stepMedia" | "stepWhere" | "stepMessage" | "stepWhen";
}

export const WIZARD_STEPS: readonly WizardStepDef[] = [
  { id: "media", labelKey: "stepMedia" },
  { id: "where", labelKey: "stepWhere" },
  { id: "message", labelKey: "stepMessage" },
  { id: "when", labelKey: "stepWhen" },
] as const;

/** Image surfaces: no caption/description/CTA is sent for these. */
export const MEDIA_ONLY_METHODS: ReadonlySet<string> = new Set([
  "story",
  "reel",
  "status",
  "gallery",
  "profile",
  "banner",
]);

/** True when a format is a text-bearing surface (caption/description apply). */
export function isTextFormat(method: string): boolean {
  return !MEDIA_ONLY_METHODS.has(method);
}

/** The message step is needed only when at least one selected format has text. */
export function needsMessageStep(methods: readonly string[]): boolean {
  return methods.some(isTextFormat);
}

/** Ordered visible steps for the current selection, numbered 1..n dynamically. */
export function wizardSteps(methods: readonly string[]): WizardStepDef[] {
  const showMessage = needsMessageStep(methods);
  return WIZARD_STEPS.filter((step) => showMessage || step.id !== "message");
}

export interface StepNav {
  index: number;
  number: number;
  total: number;
  next: WizardStepId | null;
  previous: WizardStepId | null;
}

/** Position/navigation of a step within a concrete step list. */
export function stepNav(steps: readonly WizardStepDef[], id: WizardStepId): StepNav {
  const index = Math.max(0, steps.findIndex((step) => step.id === id));
  return {
    index,
    number: index + 1,
    total: steps.length,
    next: steps[index + 1]?.id ?? null,
    previous: steps[index - 1]?.id ?? null,
  };
}
